"""
pdf_renderer.py - Markdown → PDF (via Playwright/Chromium)

Chromium 原生支持 CJK 字体，无需额外配置。
"""
from config import emit
import re
import os
from concurrent.futures import ThreadPoolExecutor

try:
    import markdown as md_lib
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False


# ─────────────────────────────────────
# Playwright 浏览器（懒加载，复用）
# ─────────────────────────────────────

import threading

_pw = None
_browser = None
_pw_thread_id = None


def _ensure_browser():
    global _pw, _browser, _pw_thread_id

    # 如果浏览器已存在但属于已死的线程，直接放弃旧实例
    if _browser is not None and threading.get_ident() != _pw_thread_id:
        _browser = None
        _pw = None

    if _browser is not None:
        try:
            _browser.contexts
            return _browser
        except Exception:
            emit("   🔄 PDF 渲染器 Playwright 已失效，正在重启...")
            try:
                _browser.close()
            except Exception:
                pass
            try:
                _pw.stop()
            except Exception:
                pass
            _browser = None
            _pw = None

    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=True)
    _pw_thread_id = threading.get_ident()
    return _browser


def cleanup_renderer():
    """关闭 Playwright 浏览器，在程序退出时调用"""
    global _pw, _browser
    if _browser:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None
    if _pw:
        try:
            _pw.stop()
        except Exception:
            pass
        _pw = None


# ─────────────────────────────────────
# 简历 CSS 样式
# ─────────────────────────────────────

RESUME_CSS = """
@page {
    size: A4;
    margin: 2cm;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: Arial, Calibri, 'Microsoft JhengHei', 'PingFang HK',
                 'PingFang SC', 'SimHei', sans-serif;
    font-size: 10.5pt;
    line-height: 1.7;
    color: #222;
    max-width: 100%;
    margin: 0;
    padding: 0;
}

h1 {
    font-size: 22pt;
    font-weight: 700;
    color: #111;
    margin-bottom: 4px;
}

h1 + p, h1 + p + p {
    color: #444;
    font-size: 10pt;
    margin-bottom: 3px;
}

h2 {
    font-size: 12pt;
    font-weight: 700;
    color: #222;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1.5px solid #333;
    padding-bottom: 3px;
    margin-top: 20px;
    margin-bottom: 10px;
}

h3 {
    font-size: 11pt;
    font-weight: 600;
    color: #222;
    margin-top: 12px;
    margin-bottom: 2px;
}

p {
    margin: 4px 0;
}

strong {
    font-weight: 600;
    color: #111;
}

em {
    font-style: italic;
    color: #444;
}

a {
    color: #222;
    text-decoration: none;
}

ul {
    margin: 4px 0 10px 0;
    padding-left: 20px;
}

li {
    margin: 4px 0;
}

hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 16px 0;
}

code {
    font-family: 'Courier New', monospace;
    font-size: 9.5pt;
}

/* ATS + 打印优化 */
@media print {
    body { padding: 0; }
    h2 { page-break-after: avoid; }
    h3 { page-break-after: avoid; }
    ul { page-break-inside: avoid; }
}
"""


# ─────────────────────────────────────
# 报告 CSS 样式
# ─────────────────────────────────────

REPORT_CSS = """
@page {
    size: A4;
    margin: 2cm;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: Arial, Calibri, 'Microsoft JhengHei', 'PingFang HK',
                 'PingFang SC', 'SimHei', sans-serif;
    font-size: 10.5pt;
    line-height: 1.7;
    color: #222;
    margin: 0;
    padding: 0;
}

h1 {
    font-size: 20pt;
    font-weight: 700;
    color: #1a5276;
    margin-bottom: 6px;
    padding-bottom: 6px;
    border-bottom: 2px solid #1a5276;
}

h2 {
    font-size: 14pt;
    font-weight: 700;
    color: #1a5276;
    margin-top: 24px;
    margin-bottom: 10px;
    padding-bottom: 4px;
    border-bottom: 1px solid #ccc;
}

h3 {
    font-size: 11pt;
    font-weight: 600;
    color: #333;
    margin-top: 14px;
    margin-bottom: 4px;
}

p {
    margin: 6px 0;
}

strong {
    font-weight: 600;
    color: #111;
}

em {
    font-style: italic;
    color: #555;
}

a {
    color: #1a5276;
    text-decoration: none;
}

ul, ol {
    margin: 6px 0 10px 0;
    padding-left: 22px;
}

li {
    margin: 4px 0;
}

hr {
    border: none;
    border-top: 1px solid #ddd;
    margin: 18px 0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 14px 0;
    font-size: 10pt;
}

th {
    background: #f0f4f8;
    font-weight: 600;
    text-align: left;
    padding: 6px 10px;
    border: 1px solid #ddd;
}

td {
    padding: 5px 10px;
    border: 1px solid #ddd;
}

tr:nth-child(even) {
    background: #fafbfc;
}

code {
    font-family: 'Courier New', monospace;
    background: #f4f4f4;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9.5pt;
}

@media print {
    body { padding: 0; }
    h1 { page-break-after: avoid; }
    h2 { page-break-after: avoid; }
    h3 { page-break-after: avoid; }
    table { page-break-inside: avoid; }
    ul { page-break-inside: avoid; }
}
"""


# ─────────────────────────────────────
# Markdown → HTML 转换
# ─────────────────────────────────────

def _inline(text: str) -> str:
    """处理内联 Markdown 语法"""
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text


def _fix_resume_markdown(md_text: str) -> str:
    """修复 LLM 输出的常见 markdown 格式问题，确保 bullet points 能正确渲染。"""
    lines = md_text.split('\n')
    fixed = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 去掉 bullet 之间的空行（避免 markdown 库生成 <li><p> 嵌套）
        if stripped == '' and fixed:
            prev = fixed[-1].strip()
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if prev.startswith(('- ', '* ')) and next_line.startswith(('- ', '* ')):
                i += 1
                continue

        fixed.append(line)
        i += 1

    return '\n'.join(fixed)


def markdown_to_html(md_text: str) -> str:
    """将 Markdown 转为 HTML（优先用 markdown 库，否则用内置转换器）"""
    md_text = _fix_resume_markdown(md_text)
    if _HAS_MARKDOWN:
        return md_lib.markdown(md_text, extensions=['extra', 'smarty', 'sane_lists'])

    # ── 内置简易转换器 ──
    lines = md_text.split('\n')
    html_parts = []
    in_ul = False

    for line in lines:
        s = line.strip()

        if not s:
            if in_ul:
                html_parts.append('</ul>')
                in_ul = False
            html_parts.append('')
            continue

        if s.startswith('### '):
            html_parts.append(f'<h3>{_inline(s[4:])}</h3>')
        elif s.startswith('## '):
            html_parts.append(f'<h2>{_inline(s[3:])}</h2>')
        elif s.startswith('# '):
            html_parts.append(f'<h1>{_inline(s[2:])}</h1>')
        elif s == '---' or s == '***':
            html_parts.append('<hr>')
        elif s.startswith(('* ', '- ')):
            if not in_ul:
                html_parts.append('<ul>')
                in_ul = True
            html_parts.append(f'<li>{_inline(s[2:])}</li>')
        else:
            html_parts.append(f'<p>{_inline(s)}</p>')

    if in_ul:
        html_parts.append('</ul>')

    return '\n'.join(html_parts)


# ─────────────────────────────────────
# 渲染：Markdown → PDF
# ─────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title} - Resume</title>
  <style>
{css}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _render_in_thread(html: str, pdf_path: str) -> str | None:
    """在独立线程中完成完整的 Playwright 渲染，避免 asyncio 事件循环冲突。"""
    from playwright.sync_api import sync_playwright
    pw = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until='networkidle')
        page.pdf(
            path=pdf_path,
            format='A4',
            margin={'top': '1.5cm', 'right': '2cm', 'bottom': '1.5cm', 'left': '2cm'},
            print_background=True,
        )
        page.close()
        browser.close()
        return pdf_path
    except Exception as e:
        emit(f"   ⚠️ 线程内 PDF 渲染失败: {e}")
        return None
    finally:
        if pw:
            try:
                pw.stop()
            except Exception:
                pass


def render_resume(md_content: str, output_path: str) -> str | None:
    """
    Markdown → PDF（通过 Playwright/Chromium 渲染）

    Args:
        md_content: Markdown 简历/Cover Letter 文本
        output_path: 输出路径基准（.md 后缀会替换为 .pdf）

    Returns:
        PDF 文件路径，失败返回 None
    """
    body = markdown_to_html(md_content)

    title_match = re.search(r'^#\s+(.+)', md_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else 'Resume'

    html = _HTML_TEMPLATE.format(title=title, css=RESUME_CSS, body=body)

    pdf_path = re.sub(r'\.md$', '.pdf', output_path)
    if pdf_path == output_path:
        pdf_path += '.pdf'

    os.makedirs(os.path.dirname(pdf_path) or '.', exist_ok=True)

    global _pw, _browser

    for attempt in range(2):
        try:
            browser = _ensure_browser()
            page = browser.new_page()
            page.set_content(html, wait_until='networkidle')
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '1.5cm', 'right': '2cm', 'bottom': '1.5cm', 'left': '2cm'},
                print_background=True,
            )
            page.close()
            return pdf_path
        except Exception as e:
            err_str = str(e)
            # asyncio 事件循环冲突 → 在独立线程中完成整个渲染
            if "Sync API" in err_str or "asyncio" in err_str.lower():
                emit(f"   🔄 检测到 asyncio 冲突，在独立线程中渲染 PDF...")
                with ThreadPoolExecutor(1) as pool:
                    return pool.submit(_render_in_thread, html, pdf_path).result()
            # 其他错误 → 重建浏览器重试一次
            if attempt == 0:
                emit(f"   🔄 PDF 渲染失败，重建浏览器重试...")
                try:
                    _browser.close()
                except Exception:
                    pass
                try:
                    _pw.stop()
                except Exception:
                    pass
                _browser = None
                _pw = None
            else:
                emit(f"   ⚠️ PDF 生成失败: {e}")
                return None


def render_report(md_content: str, output_path: str) -> str | None:
    """
    Markdown 报告 → PDF（使用报告专用样式）

    与 render_resume 的区别：使用 REPORT_CSS（带表格、更大标题间距、章节风格）
    """
    body = markdown_to_html(md_content)

    title_match = re.search(r'^#\s+(.+)', md_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else 'Report'

    html = _HTML_TEMPLATE.format(title=title, css=REPORT_CSS, body=body)

    pdf_path = re.sub(r'\.md$', '.pdf', output_path)
    if pdf_path == output_path:
        pdf_path += '.pdf'

    os.makedirs(os.path.dirname(pdf_path) or '.', exist_ok=True)

    global _pw, _browser

    for attempt in range(2):
        try:
            browser = _ensure_browser()
            page = browser.new_page()
            page.set_content(html, wait_until='networkidle')
            page.pdf(
                path=pdf_path,
                format='A4',
                margin={'top': '2cm', 'right': '2cm', 'bottom': '2cm', 'left': '2cm'},
                print_background=True,
            )
            page.close()
            return pdf_path
        except Exception as e:
            err_str = str(e)
            if "Sync API" in err_str or "asyncio" in err_str.lower():
                emit(f"   🔄 检测到 asyncio 冲突，在独立线程中渲染 PDF...")
                with ThreadPoolExecutor(1) as pool:
                    return pool.submit(_render_in_thread, html, pdf_path).result()
            if attempt == 0:
                emit(f"   🔄 PDF 渲染失败，重建浏览器重试...")
                try:
                    _browser.close()
                except Exception:
                    pass
                try:
                    _pw.stop()
                except Exception:
                    pass
                _browser = None
                _pw = None
            else:
                emit(f"   ⚠️ PDF 生成失败: {e}")
                return None
