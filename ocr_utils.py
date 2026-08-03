"""
ocr_utils.py — OCR 工具层

职责：从图片/PDF 提取纯文本。引擎可切换（默认 tesseract）。

对外接口：
    extract_text(file_bytes, filename) → OCRResult

内部预处理管道：
    图片 → 灰度化 → 自适应二值化 → DPI 放大 → 去噪 → CLAHE 对比度增强 → OCR

设计原则：
    - OCR 不做事后纠错（LLM 在 generate_resume 中自然容错）
    - PDF 优先从文字层提取（快且准），扫描件才走 OCR
    - Tesseract 未安装时给出清晰指引，不静默失败
"""

import io
import os
import time
import shutil
import logging
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageFilter, ImageOps
import pytesseract

# ── Tesseract 检测 ──

# Windows 常见安装路径（按优先级排列）
_KNOWN_TESSERACT_PATHS = [
    # 用户在安装时可自定义路径
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    # 通过 MSYS2 / Git Bash 安装
    r"C:\msys64\mingw64\bin\tesseract.exe",
    r"C:\msys64\usr\bin\tesseract.exe",
    # winget 安装（UB-Mannheim 版本）
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]

_TESSERACT_EXE = None  # 已定位的 tesseract 路径（或 None 表示未安装）


def _detect_tesseract() -> str | None:
    """定位 tesseract 二进制。按优先级：环境变量 > PATH > 已知路径 > shutil.which。

    返回可执行文件的完整路径，未找到则返回 None。
    """
    # 1. 环境变量 TESSERACT_CMD（用户显式指定）
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd and os.path.isfile(env_cmd):
        return env_cmd

    # 2. PATH 或当前 pytesseract 能定位
    try:
        detected = pytesseract.pytesseract.tesseract_cmd
        if detected and os.path.isfile(detected):
            return detected
    except Exception:
        pass

    # 3. 已知安装路径
    for p in _KNOWN_TESSERACT_PATHS:
        if os.path.isfile(p):
            return p

    # 4. shutil.which（系统级搜索）
    found = shutil.which("tesseract")
    if found and os.path.isfile(found):
        return found

    return None


def _set_tesseract_path(exe_path: str | None) -> None:
    """配置 pytesseract 使用指定的 tesseract 可执行文件。"""
    global _TESSERACT_EXE
    if exe_path and os.path.isfile(exe_path):
        pytesseract.pytesseract.tesseract_cmd = exe_path
        _TESSERACT_EXE = exe_path
    else:
        _TESSERACT_EXE = None


_TESSERACT_EXE = _detect_tesseract()
_set_tesseract_path(_TESSERACT_EXE)


def is_tesseract_available() -> bool:
    """检测 Tesseract OCR 引擎是否可用。"""
    return _TESSERACT_EXE is not None


def get_tesseract_status() -> str:
    """返回 Tesseract 安装状态文本（供启动日志和 API 响应使用）。"""
    if _TESSERACT_EXE:
        try:
            import subprocess
            result = subprocess.run([_TESSERACT_EXE, "--version"],
                                    capture_output=True, text=True, timeout=5)
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            return f"Tesseract 已就绪 ({_TESSERACT_EXE}): {version_line}"
        except Exception:
            return f"Tesseract 已找到但无法获取版本 ({_TESSERACT_EXE})"
    else:
        return (
            "Tesseract-OCR 未安装。\n"
            "安装方法（Windows）：\n"
            "  1. 下载安装包: https://github.com/UB-Mannheim/tesseract/releases\n"
            "     推荐: tesseract-ocr-w64-setup-5.4.0.20240606.exe\n"
            "  2. 安装时勾选中文语言包 (Chinese Simplified / Chinese Traditional)\n"
            "  3. 安装后重启本应用\n"
            "  4. 或设置环境变量 TESSERACT_CMD=安装路径\\tesseract.exe"
        )


# ── 输出结构 ──

class OCRResult(NamedTuple):
    text: str           # 提取到的纯文本（失败时为空字符串）
    engine: str         # 使用的引擎名（"tesseract" / "pymupdf_text" / "unknown"）
    elapsed_ms: float   # 耗时（毫秒）
    error: str | None   # 错误信息（成功时为 None）


# ── 图片预处理 ──

def _preprocess_image(img: Image.Image) -> Image.Image:
    """对图片做 OCR 友好的预处理管道。

    步骤：
        1. 灰度化（统一到单通道）
        2. 放大至 DPI ≥ 300（微信/手机截图通常 72 DPI）
        3. CLAHE 对比度增强（增加文字与背景的对比）
        4. 自适应二值化（大津法，去除渐变背景和噪点）
        5. 中值滤波去噪

    各步骤独立 try/except —— 单步失败跳过，不影响后续。
    """
    # 1. 灰度化
    if img.mode == "RGBA":
        # RGBA → RGB（白色背景合成），再灰度
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])  # alpha channel as mask
        img = bg
    if img.mode != "L":
        img = img.convert("L")

    # 2. 放大至 DPI ≥ 300
    try:
        dpi = img.info.get("dpi", (72, 72))
        current_dpi = dpi[0] if isinstance(dpi, (tuple, list)) else dpi
        if current_dpi < 300:
            scale = max(1, round(300 / current_dpi))
            if scale > 1:
                w, h = img.size
                img = img.resize((w * scale, h * scale), Image.LANCZOS)
    except Exception:
        pass  # DPI 信息不可靠，保持原样

    # 3. CLAHE 对比度增强
    try:
        # Pillow 没有内置 CLAHE；用 ImageOps.equalize + 限制性对比度拉伸模拟
        # 核心思路：拉伸中间值范围，但不丢失极端值
        img = ImageOps.autocontrast(img, cutoff=2)  # 裁剪 2% 的极端像素
    except Exception:
        pass

    # 4. 自适应二值化（大津法）
    try:
        # Pillow 的 point() 配合 histogram 实现二值化
        # 大津法阈值 = 最大化类间方差
        hist = img.histogram()
        total = sum(hist)
        if total > 0:
            sum_b = 0
            w_b = 0
            max_var = 0
            threshold = 128  # 默认
            sum_total = sum(i * h for i, h in enumerate(hist))
            for t in range(256):
                w_b += hist[t]
                if w_b == 0 or w_b == total:
                    continue
                w_f = total - w_b
                sum_b += t * hist[t]
                m_b = sum_b / w_b
                m_f = (sum_total - sum_b) / w_f
                var_between = w_b * w_f * (m_b - m_f) ** 2
                if var_between > max_var:
                    max_var = var_between
                    threshold = t
            img = img.point(lambda x: 255 if x >= threshold else 0, mode="1")
            img = img.convert("L")  # 转回灰度供后续处理
    except Exception:
        # 二值化失败 → 简单阈值
        try:
            img = img.point(lambda x: 255 if x >= 128 else 0, mode="1").convert("L")
        except Exception:
            pass

    # 5. 中值滤波去噪
    try:
        img = img.filter(ImageFilter.MedianFilter(3))
    except Exception:
        pass

    return img


# ── PDF 文字层提取 ──

def _extract_text_from_pdf_text_layer(file_bytes: bytes) -> str | None:
    """尝试从 PDF 文字层提取文本（非 OCR，速度极快）。

    使用 pymupdf (fitz) —— 如果已安装。未安装则返回 None。
    如果提取出的文字 < 50 字符，视为扫描件 PDF，返回 None 让上游走 OCR。
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return None

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text.strip())
        doc.close()
        combined = "\n\n".join(pages)
        # 扫描件 PDF 几乎提取不到文字
        if len(combined.strip()) < 50:
            return None
        return combined
    except Exception:
        return None


def _extract_text_from_pdf_as_images(file_bytes: bytes) -> OCRResult:
    """将 PDF 逐页渲染为图片，再逐页 OCR。

    仅在文字层提取失败时作为备选路径。
    """
    try:
        import fitz
    except ImportError:
        return OCRResult(
            text="", engine="unknown",
            elapsed_ms=0,
            error="PDF 处理需要 pymupdf：pip install pymupdf"
        )

    t_start = time.perf_counter()
    all_text = []
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page_idx, page in enumerate(doc):
            # 渲染为图片（300 DPI）
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img = _preprocess_image(img)
            page_text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            if page_text.strip():
                all_text.append(f"--- 第{page_idx + 1}页 ---\n{page_text.strip()}")
        doc.close()
    except Exception as e:
        elapsed = (time.perf_counter() - t_start) * 1000
        return OCRResult(text="", engine="tesseract", elapsed_ms=elapsed, error=str(e))

    elapsed = (time.perf_counter() - t_start) * 1000
    text = "\n\n".join(all_text)
    if not text.strip():
        return OCRResult(
            text="", engine="tesseract", elapsed_ms=elapsed,
            error="PDF 各页均未识别到文字，可能为空白页或图片质量过低"
        )
    return OCRResult(text=text, engine="tesseract", elapsed_ms=elapsed, error=None)


# ── 后处理 ──

def _postprocess(text: str) -> str:
    """OCR 后处理：去除明显噪点，保留原有结构。

    不做的事：
        - 不做拼写纠错（LLM 能自然容错）
        - 不做段落重组（保留原始换行供 LLM 理解结构）
    """
    # 去除连续 3 个以上的空行
    import re
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    # 去除行首行尾空白
    lines = [line.rstrip() for line in text.split("\n")]
    # 去除纯空白行在开头和结尾
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


# ── 主入口 ──

# 允许的文件扩展名
_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
# 允许的 MIME 类型 magic bytes
_IMAGE_MAGIC = {
    b"\x89PNG": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"RIFF": ".webp",  # 需要进一步检查 WEBP 子类型
}
_PDF_MAGIC = b"%PDF"

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _detect_format(filename: str, file_bytes: bytes) -> str | None:
    """根据扩展名和 magic bytes 双重检测文件格式。

    返回小写扩展名（含点号，如 ".png"），无法识别返回 None。
    """
    ext = os.path.splitext(filename)[1].lower()

    # 第一层：扩展名校验
    if ext in _ALLOWED_EXTENSIONS:
        # 第二层：magic bytes 验证
        if ext == ".pdf":
            return ".pdf" if file_bytes[:4] == _PDF_MAGIC else None
        elif ext == ".webp":
            # WebP: RIFF....WEBP
            if file_bytes[:4] == b"RIFF" and len(file_bytes) > 8 and file_bytes[8:12] == b"WEBP":
                return ".webp"
            return None
        else:
            # PNG/JPG 用 magic bytes 验证
            for magic, fmt in _IMAGE_MAGIC.items():
                if file_bytes[:len(magic)] == magic:
                    return fmt
            return None  # magic 不匹配，拒绝

    return None  # 扩展名不在白名单


def extract_text(file_bytes: bytes, filename: str) -> OCRResult:
    """从图片或 PDF 文件中提取纯文本。

    Args:
        file_bytes: 文件原始字节
        filename:   原始文件名（用于判断格式）

    Returns:
        OCRResult — .text 为提取的文本（失败时为空字符串）

    格式支持：PNG, JPG, JPEG, WebP, PDF
    单文件大小上限：20 MB
    """
    # ── 校验 ──
    filename = filename or "unknown.png"

    if len(file_bytes) > _MAX_FILE_SIZE:
        return OCRResult(
            text="", engine="unknown", elapsed_ms=0,
            error=f"文件过大（{len(file_bytes) / 1024 / 1024:.1f} MB），上限 20 MB"
        )

    fmt = _detect_format(filename, file_bytes)
    if fmt is None:
        return OCRResult(
            text="", engine="unknown", elapsed_ms=0,
            error=f"不支持的文件格式：{os.path.splitext(filename)[1] or '未知'}。"
                  f"支持 PNG / JPG / WebP / PDF"
        )

    if not is_tesseract_available():
        return OCRResult(
            text="", engine="unknown", elapsed_ms=0,
            error="Tesseract-OCR 未安装。请在 Web 启动日志中查看安装指引，"
                  "或手动粘贴 JD 文本。"
        )

    # ── PDF 路径 ──
    if fmt == ".pdf":
        # 优先文字层提取（快且准）
        text = _extract_text_from_pdf_text_layer(file_bytes)
        if text:
            t_start = time.perf_counter()
            text = _postprocess(text)
            elapsed = (time.perf_counter() - t_start) * 1000
            return OCRResult(text=text, engine="pymupdf_text", elapsed_ms=elapsed, error=None)
        # 扫描件 PDF → 逐页 OCR
        result = _extract_text_from_pdf_as_images(file_bytes)
        if result.error is None and result.text:
            text = _postprocess(result.text)
            result = OCRResult(text=text, engine=result.engine,
                              elapsed_ms=result.elapsed_ms, error=None)
        return result

    # ── 图片路径 ──
    t_start = time.perf_counter()
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = _preprocess_image(img)
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        elapsed = (time.perf_counter() - t_start) * 1000
        text = _postprocess(text)

        if not text.strip():
            return OCRResult(
                text="", engine="tesseract", elapsed_ms=elapsed,
                error="OCR 未识别到文字。请确认截图清晰完整、包含中文或英文，"
                      "或手动粘贴 JD 文本。"
            )

        # 文字太少 → 警告但不过滤（用户可能上传了极简 JD）
        char_count = len(text.strip())
        if char_count < 50:
            return OCRResult(
                text=text, engine="tesseract", elapsed_ms=elapsed,
                error=f"⚠️ 仅识别到 {char_count} 个字符，结果可能不完整。"
                      "建议确认截图是否清晰完整。"
            )

        return OCRResult(text=text, engine="tesseract", elapsed_ms=elapsed, error=None)

    except Exception as e:
        elapsed = (time.perf_counter() - t_start) * 1000
        return OCRResult(text="", engine="tesseract", elapsed_ms=elapsed, error=str(e))
