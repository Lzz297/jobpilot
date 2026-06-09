"""
checker.py — 简历 bullet 事实核查

对 LLM 生成的简历 bullet 与用户档案中的源条目进行比对，
检测数字矛盾、强度升级、占位符残留等问题。
"""
import re


# ============================================================
#  动词强度映射表
# ============================================================

VERB_STRENGTH = {
    # 低强度（1）
    "参与": 1, "协助": 1, "了解": 1, "学习": 1, "跟进": 1,
    "assisted": 1, "participated": 1, "supported": 1, "observed": 1,
    "helped": 1, "joined": 1, "attended": 1, "followed": 1,
    # 中强度（2）
    "负责": 2, "编写": 2, "开发": 2, "维护": 2, "设计": 2, "实现": 2, "构建": 2,
    "developed": 2, "implemented": 2, "built": 2, "wrote": 2, "maintained": 2,
    "created": 2, "managed": 2, "delivered": 2, "handled": 2, "configured": 2,
    "integrated": 2, "deployed": 2, "tested": 2, "optimized": 2, "authored": 2,
    # 高强度（3）
    "主导": 3, "架构": 3, "领导": 3, "创建": 3, "革新": 3, "重建": 3, "带领": 3,
    "led": 3, "architected": 3, "designed": 3, "owned": 3, "established": 3,
    "engineered": 3, "directed": 3, "spearheaded": 3, "orchestrated": 3,
    "pioneered": 3, "drove": 3, "headed": 3, "championed": 3,
}


# ============================================================
#  占位符检测模式
# ============================================================

_PLACEHOLDER_PATTERNS = [
    re.compile(r"\[请在此[^\]]*\]"),
    re.compile(r"【待补充[^】]*】"),
    re.compile(r"\[TODO[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[TBD[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[待填[^\]]*\]"),
    re.compile(r"\[在此[^\]]*\]"),
]


# ============================================================
#  数字 / 约数处理工具
# ============================================================

# 中文数字映射
_CN_NUM_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
}

# 约数前缀模式
_APPROX_PREFIXES = re.compile(r"^(约|大约|大概|近|将近|差不多|约莫|左右)")

# 中文数字+单位模式（如"一年半"、"五千"、"1.5万"）
_CN_NUMBER_PATTERN = re.compile(
    r"(约|大约|大概|近)?\s*"
    r"([零一二两三四五六七八九十百千万亿\d]+\.?\d*)"
    r"\s*(百|千|万|亿|%|％|年|月|天|小时|分钟|秒|个|名|位|次|倍|元|块|美金|美元)?"
)

# 标准数字提取（含小数、约数前缀）
_NUMBER_PATTERN = re.compile(
    r"(约|大约|大概|近|约莫)?\s*"
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(%|％|万|千|百|k|K|m|M|w|W|年|月|天|小时|分钟|秒|个|名|位|次|倍|元|块|美金|美元|TPS|tps)?"
)


def _extract_numbers(text: str) -> list[dict]:
    """从文本中提取所有数字，返回 [{value, unit, is_approx, original}]。"""
    results = []
    # 先尝试中文数字
    cn_matches = _CN_NUMBER_PATTERN.finditer(text)
    for m in cn_matches:
        is_approx = bool(m.group(1))
        cn_str = m.group(2)
        unit = m.group(3) or ""
        # 如果全是数字字符（非中文数字），用标准模式处理
        if re.match(r"^[\d.]+$", cn_str):
            val = float(cn_str)
            # 处理单位换算
            if unit in ("万",):
                val *= 10000
            elif unit in ("千",):
                val *= 1000
            elif unit in ("百",):
                val *= 100
            elif unit in ("k", "K"):
                val *= 1000
            elif unit in ("m", "M"):
                val *= 1000000
            results.append({
                "value": val,
                "unit": unit,
                "is_approx": is_approx,
                "original": m.group(0),
            })
            continue

        # 解析中文数字串
        val = _parse_cn_number(cn_str)
        if val is not None:
            if unit in ("万",):
                val *= 10000
            elif unit in ("千",):
                val *= 1000
            elif unit in ("百",):
                val *= 100
            results.append({
                "value": float(val),
                "unit": unit,
                "is_approx": is_approx,
                "original": m.group(0),
            })
    return results


def _parse_cn_number(s: str) -> int | None:
    """解析纯中文数字串（如"一千五百"→1500、"三点五"→3.5）。"""
    if not s:
        return None
    total = 0
    current = 0
    for ch in s:
        if ch in _CN_NUM_MAP:
            v = _CN_NUM_MAP[ch]
            if v >= 10:  # 单位（十、百、千、万、亿）
                if current == 0:
                    current = 1
                current *= v
                if v >= 10000:  # 万、亿分段
                    total += current
                    current = 0
            else:
                current = v
        elif ch == "点":
            # 小数简化为取整（"一点五" ≈ 1.5）
            # 实际中很少遇到，暂不处理
            pass
        else:
            return None
    total += current
    return total if total > 0 else None


def _chinese_num_to_value(text: str) -> float | None:
    """将中文数字表达转换为浮点值。支持"一年半"→1.5、"三千"→3000。"""
    # "一年半" → 1.5
    match = re.match(r"^一([个位名])半$", text)
    if match:
        return 1.5
    match = re.match(r"^两([个位名])半$", text)
    if match:
        return 2.5
    # 通用中文数字
    return None


def _numbers_equivalent(a: float, b: float) -> bool:
    """判断两个数字是否等值（考虑百分比 vs 小数的转换）。"""
    if abs(a - b) < 0.001:
        return True
    # 百分比 ↔ 小数：50% = 0.5
    if abs(a - b * 100) < 0.001:
        return True
    if abs(b - a * 100) < 0.001:
        return True
    # 万单位 ↔ 纯数字：1万 = 10000
    if abs(a - b * 10000) < 0.001:
        return True
    if abs(b - a * 10000) < 0.001:
        return True
    return False


# ============================================================
#  强度核查
# ============================================================

def _first_verb_strength(text: str) -> int:
    """提取文本中第一个谓语动词的强度值。中文取首动词，英文取首动词。"""
    # 中文：取第一个匹配的动词
    best = 0
    text_lower = text.lower()
    for verb, level in VERB_STRENGTH.items():
        if verb.lower() in text_lower:
            best = max(best, level)
    return best


def _max_verb_strength(texts: list[str]) -> int:
    """取多条源文本中谓语动词的最高强度。"""
    best = 0
    for t in texts:
        best = max(best, _first_verb_strength(t))
    return best


# ============================================================
#  源条目查找
# ============================================================

def _find_source_texts(profile: dict, source_ids: list[str]) -> list[str]:
    """在用户画像中按 source_ids 查找对应的原文。"""
    results = []
    # 搜索路径 1: experiences（mock_me.yaml 格式）
    experiences = profile.get("experiences", [])
    for exp in experiences:
        eid = exp.get("id", "")
        if eid in source_ids:
            results.append(exp.get("text", ""))

    # 搜索路径 2: work_experience → core_modules → resume_bullet_candidates（me.yaml 格式）
    for we in profile.get("work_experience", []):
        # core_modules
        for mod_name, mod_data in we.get("core_modules", {}).items():
            for bullet in mod_data.get("resume_bullet_candidates", []):
                if isinstance(bullet, dict) and bullet.get("id") in source_ids:
                    results.append(bullet.get("text", ""))
                elif isinstance(bullet, str):
                    # 旧格式（纯字符串，无 id），跳过
                    pass
        # key_achievements
        for ka in we.get("key_achievements", []):
            if ka.get("id") in source_ids:
                results.append(ka.get("resume_bullet", ""))
        # highlights（旧格式无 id，跳过）
        # 但可以通过 id 匹配

    # 搜索路径 3: projects → resume_bullets
    for proj in profile.get("projects", []):
        for bullet in proj.get("resume_bullets", []):
            if isinstance(bullet, dict) and bullet.get("id") in source_ids:
                results.append(bullet.get("text", ""))

    return results


# ============================================================
#  主函数
# ============================================================

def check_bullet(source_ids: list[str], profile: dict, bullet_text: str) -> list[str]:
    """
    对一条简历 bullet 进行事实核查。

    Args:
        source_ids: bullet 声称引用的 profile 条目 id 列表
        profile: 用户画像字典（me.yaml 或 mock_me.yaml 的内容）
        bullet_text: 简历 bullet 的文本

    Returns:
        list[str]: 检测到的 flag 列表。无问题时返回 []。
    """
    flags = []

    # ── 0. dangling_reference / empty_source ──
    if not source_ids or len(source_ids) == 0:
        flags.append("empty_source")
        return flags  # 空 source_ids 自身就是唯一的 flag

    # 收集所有可用的 id
    available_ids = set()
    # experiences（mock 格式）
    for exp in profile.get("experiences", []):
        available_ids.add(exp.get("id", ""))
    # core_modules bullet candidates
    for we in profile.get("work_experience", []):
        for mod_data in we.get("core_modules", {}).values():
            for bullet in mod_data.get("resume_bullet_candidates", []):
                if isinstance(bullet, dict):
                    available_ids.add(bullet.get("id", ""))
        for ka in we.get("key_achievements", []):
            available_ids.add(ka.get("id", ""))
    # projects
    for proj in profile.get("projects", []):
        for bullet in proj.get("resume_bullets", []):
            if isinstance(bullet, dict):
                available_ids.add(bullet.get("id", ""))

    has_dangling = False
    for sid in source_ids:
        if sid not in available_ids:
            has_dangling = True
            break
    if has_dangling:
        flags.append("dangling_reference")

    # 获取源文本
    source_texts = _find_source_texts(profile, source_ids)

    # ── 1. 占位符检测 ──
    for pat in _PLACEHOLDER_PATTERNS:
        if pat.search(bullet_text):
            flags.append("placeholder_present")
            break

    # ── 2. 数字核查 ──
    bullet_nums = _extract_numbers(bullet_text)
    source_nums = []
    source_raw = " ".join(source_texts)
    source_nums = _extract_numbers(source_raw)

    # 同时检查中文同义数字
    # "一年半" = 1.5
    cn_special = {
        "一年半": 1.5, "两年半": 2.5, "三年半": 3.5, "四年半": 4.5, "五年半": 5.5,
        "半个月": 0.5, "一个半月": 1.5, "两个半月": 2.5,
    }
    has_cn_special_match = False
    for cn_text, cn_val in cn_special.items():
        if cn_text in bullet_text:
            bullet_nums.append({"value": cn_val, "unit": "年", "is_approx": False, "original": cn_text})
            has_cn_special_match = True
        if cn_text in source_raw:
            source_nums.append({"value": cn_val, "unit": "年", "is_approx": False, "original": cn_text})
    # 如果有完整的中文数字短语匹配，过滤掉正则匹配到的部分结果（如"一年"被"一年半"覆盖）
    if has_cn_special_match:
        bullet_nums = [n for n in bullet_nums if not (
            n["original"] in ("一年", "两年", "三年", "四年", "五年", "半个")
            and n["unit"] == "年"
        )]

    if bullet_nums:
        # 如果源中没有任何数字
        if not source_nums:
            # 检查 bullet 中的数字是否可能在源中以中文形式存在但未被提取
            # 如果源文本长度>0且没有任何数字，报 number_not_found
            has_any_source_num = bool(re.search(r"\d", source_raw))
            if not has_any_source_num:
                flags.append("number_not_found")
        else:
            # 逐条比较
            for bn in bullet_nums:
                found_match = False
                for sn in source_nums:
                    # 精确等值
                    if _numbers_equivalent(bn["value"], sn["value"]):
                        found_match = True
                        break
                    # 约数 ±5% 容差
                    if bn["is_approx"] or sn["is_approx"]:
                        if sn["value"] != 0:
                            pct_diff = abs(bn["value"] - sn["value"]) / sn["value"]
                            if pct_diff <= 0.05:
                                found_match = True
                                break
                    # 直接数字比较（同单位或从原文本判断是同一数字）
                    if bn["unit"] == sn["unit"]:
                        continue  # 上面已经检查过等值，这里不需要再做

                if not found_match:
                    # 检查是否同义改写（中文数字 ↔ 阿拉伯数字）
                    # 已通过 _extract_numbers 和 cn_special 处理
                    # 判定冲突类型
                    if bn["is_approx"]:
                        # 约数未找到匹配 → 可能超出容差
                        for sn in source_nums:
                            if sn["unit"] == bn["unit"] and sn["value"] != 0:
                                pct = abs(bn["value"] - sn["value"]) / sn["value"]
                                if pct > 0.05:
                                    if "approx_out_of_range" not in flags:
                                        flags.append("approx_out_of_range")
                                    found_match = True
                                    break
                        if not found_match:
                            flags.append("number_not_found")
                    else:
                        # 精确数字冲突
                        # 先检查是否有同单位的近似数字
                        has_nearby = False
                        for sn in source_nums:
                            if sn["unit"] == bn["unit"] and sn["value"] != 0:
                                has_nearby = True
                                if abs(bn["value"] - sn["value"]) > 0.001:
                                    flags.append("number_conflict")
                                    found_match = True
                                    break
                        if not found_match and not has_nearby:
                            flags.append("number_not_found")

    # ── 3. 强度核查 ──
    if source_texts:
        source_max_strength = _max_verb_strength(source_texts)
        bullet_strength = _first_verb_strength(bullet_text)
        if bullet_strength > source_max_strength and source_max_strength > 0:
            flags.append("strength_upgrade")

    return flags
