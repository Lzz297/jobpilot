"""
job_match.py - LLM 多维度匹配评分 + 结果查看
"""
import os
import json
import yaml
from datetime import datetime

from config import (
    emit, llm_call, OUTPUT_DIR, track_file,
    load_profile, load_search_config_dict,
    get_current_run_dir, get_latest_run_dir, load_prompts, render_prompt,
    get_llm_concurrency, run_batches_concurrently,
    DIAGNOSE_MODE, get_last_usage, get_last_raw_response_text,
)
from scraper import normalize_jobsdb_url
import threading


# ── 模块级兜底记录列表（并发写入需加锁）──
_fallback_lock = threading.Lock()
_dir_fallbacks = []
_weight_fallbacks = []
_score_errors = []


# ============================================================
#  岗位分类 & 动态权重
# ============================================================

# 分类检查顺序：从 weight_rules 动态派生，排除 "default"，按 key 长度降序
# （更具体的类别在前，通用类别在后）


def classify_job(title, weight_rules):
    """根据岗位标题关键词匹配权重类型。分类顺序从 weight_rules keys 动态派生。"""
    title_lower = title.lower()
    order = sorted(
        [k for k in weight_rules if k != "default"],
        key=lambda k: (-len(k), k)
    )
    for category in order:
        keywords = weight_rules.get(category, [])
        for kw in keywords:
            if kw.lower() in title_lower:
                return category
    return "default"


def get_weights(profile_name, weight_profiles):
    """获取指定方向的权重字典，带五维校验和兜底。

    返回 (weights_dict, source_label)。
    校验规则：五维 key（skill/experience/level/industry/bonus）必须齐全，且值之和等于 100。
    任一不满足 → 视为无效，逐级回退。
    """
    REQUIRED_KEYS = {"skill", "experience", "level", "industry", "bonus"}
    HARDCODED_DEFAULT = {"skill": 30, "experience": 25, "level": 15, "industry": 15, "bonus": 15}

    def _validate(w):
        """权重字典合法：非空、五维齐全、和为 100"""
        if not w or not isinstance(w, dict):
            return False
        return set(w.keys()) == REQUIRED_KEYS and sum(w.values()) == 100

    # 1. 尝试 weight_profiles[profile_name]
    w = weight_profiles.get(profile_name)
    if _validate(w):
        return w, f"数据库策略 {profile_name}"

    # 2. 回退到 weight_profiles["default"]
    w = weight_profiles.get("default")
    if _validate(w):
        return w, "策略 default"

    # 3. 硬编码兜底
    return dict(HARDCODED_DEFAULT), f"代码默认值 · 策略 {profile_name} 未配置权重"


def _build_weights_text(weights):
    """将权重字典格式化为 prompt 中的权重描述。"""
    return (
        f"1. 技能匹配 (权重 {weights['skill']}%): JD 要求的编程语言、框架、工具，候选人掌握了多少？\n"
        f"2. 经验匹配 (权重 {weights['experience']}%): 工作年限是否达标？行业经验是否对口？\n"
        f"3. 职级匹配 (权重 {weights['level']}%): 岗位级别与候选人水平是否匹配？\n"
        f"4. 行业匹配 (权重 {weights['industry']}%): 岗位所在行业与候选人背景和意向是否吻合？\n"
        f"5. 加分项   (权重 {weights['bonus']}%): 认证、语言能力、地点便利性等"
    )


def _build_score_formula(weights):
    """将权重字典格式化为 total_score 计算公式文本。"""
    return (
        f"skill*{weights['skill']/100:.2f} + experience*{weights['experience']/100:.2f} + "
        f"level*{weights['level']/100:.2f} + industry*{weights['industry']/100:.2f} + "
        f"bonus*{weights['bonus']/100:.2f}"
    )


def _calc_total_score(scores, weights):
    """根据权重手动计算加权总分（四舍五入取整）。用于同档位内的排序。"""
    return round(
        scores.get("skill", 0) * weights["skill"] / 100 +
        scores.get("experience", 0) * weights["experience"] / 100 +
        scores.get("level", 0) * weights["level"] / 100 +
        scores.get("industry", 0) * weights["industry"] / 100 +
        scores.get("bonus", 0) * weights["bonus"] / 100
    )


def _determine_level_by_discrete_scores(scores_dict):
    """
    基于 LLM 输出的强制阶梯离散分，进行最终档位判定。

    设计原则：档位回答"候选人能否胜任"。能力维度（skill/exp/level/industry）
    决定档位上下限，bonus 维度仅在触发致命风险（20）或高风险（40）时进行降级。
    """
    skill = scores_dict.get("skill", 60)
    exp   = scores_dict.get("experience", 60)
    level = scores_dict.get("level", 60)
    industry = scores_dict.get("industry", 60)
    bonus = scores_dict.get("bonus", 60)

    # 红线 1: 叹息之墙绝对硬伤
    if exp == 20 or level == 20 or skill == 20:
        return "Low"

    # 红线 2: 核心技术栈缺失 或 转型红线彻底失败
    if skill == 40 or exp == 40:
        return "Low"

    # 红线 3: 面试/英语致命风险
    if bonus == 20:
        return "Low"

    # 能力维度检查：skill/exp/level/industry 是否有短板（40 或 60）
    capability_dims = [skill, exp, level, industry]
    has_capability_gap = any(v in (40, 60) for v in capability_dims)

    # bonus 高风险检查（40 分视为有不容忽视的风险，限制为 Medium）
    has_bonus_risk = (bonus == 40)

    if has_capability_gap or has_bonus_risk:
        return "Medium"

    # 能力维度全 >= 80 且 bonus 无致命/高风险 → 胜任
    return "High"


# ============================================================
#  LLM 评分（单批次）
# ============================================================


def _load_scoring_prompt():
    """加载匹配评分 prompt。唯一来源为 prompts.yaml。"""
    template = load_prompts().get("job_match", {}).get("scoring_system_prompt")
    if not template:
        raise RuntimeError("job_match.scoring_system_prompt 在 prompts.yaml 中缺失或为空")
    return template


def _load_direction_prompt():
    """加载方向分类 prompt。唯一来源为 prompts.yaml。"""
    template = load_prompts().get("job_match", {}).get("direction_classification_prompt")
    if not template:
        raise RuntimeError("job_match.direction_classification_prompt 在 prompts.yaml 中缺失或为空")
    return template


def classify_direction_batch(jobs, config):
    """对一批 JD 调用 LLM 做方向分类，返回带有 llm_direction 字段的 JD 列表。

    Args:
        jobs: raw_jobs.json 的内容列表（URL 已去重，每个条目含 index 字段）
        config: Campaign 配置字典

    Returns:
        带有 llm_direction 字段的 JD 列表（原地修改 + 返回）
    """
    matching_cfg = (config or {}).get("matching", {})
    weight_rules = matching_cfg.get("weight_rules", {})
    weight_profiles = matching_cfg.get("weight_profiles", {})

    # ── 1. 构建方向列表 ──
    direction_names = [k for k in weight_profiles.keys() if k != "default"]
    if "default" not in direction_names:
        direction_names.append("default")
    direction_list = " / ".join(direction_names)

    # ── 2. 加载并渲染 prompt ──
    template = _load_direction_prompt()
    system_prompt = render_prompt(template,
        direction_list=direction_list,
    )

    # 注入公共 few-shot 示例（仅一次）
    common_text = _load_common_direction_examples()
    if common_text:
        system_prompt += "\n\n" + common_text

    # 注入各方向专属 few-shot 示例
    for dir_name in direction_names:
        dir_text = _load_direction_examples(dir_name)
        if dir_text:
            system_prompt += "\n\n" + dir_text

    # ── 3. 构建所有批次的 thunk 列表 ──
    direction_batch_size = (config or {}).get("matching", {}).get("direction_batch_size", 20)
    jd_max_chars = (config or {}).get("search", {}).get("jd_max_chars", 4000)
    valid_directions = set(weight_rules.keys()) | {"default"}

    batches = []
    thunks = []

    for i in range(0, len(jobs), direction_batch_size):
        batch = jobs[i:i + direction_batch_size]
        batches.append(batch)
        batch_num = i // direction_batch_size + 1

        def _make_direction_thunk(_batch=batch, _bn=batch_num):
            """闭包捕获当前批次数据，返回无参 callable"""
            jobs_text = ""
            for j, job in enumerate(_batch):
                job_idx = job.get("index", 0)
                jobs_text += f"\n--- 岗位 {job_idx} ---\n"
                jobs_text += f"标题: {job.get('title', '未知')}\n"
                if job.get("company"):
                    jobs_text += f"公司: {job['company']}\n"
                desc = job.get("description", "")
                if len(desc) > jd_max_chars:
                    desc = desc[:jd_max_chars] + "\n...(截断)"
                jobs_text += f"职位描述:\n{desc}\n"

            def _run():
                try:
                    from engine.contracts import DirectionLabel
                    results = llm_call(
                        [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": jobs_text}],
                        temperature=0, thinking={"type": "disabled"},
                        response_model=list[DirectionLabel],
                    )
                    return [m.model_dump() for m in results]
                except Exception as e:
                    emit(f"   ❌ 方向分类 第{_bn}批失败: {e}")
                    return None  # None 表示本批失败，下游走 keyword fallback

            return _run

        thunks.append(_make_direction_thunk())

    # ── 4. 并发执行 ──
    concurrency = get_llm_concurrency()
    batch_results = run_batches_concurrently(
        thunks,
        max_workers=min(concurrency, len(thunks)),
        description="方向分类",
    )

    # ── 5. 合并结果 ──
    all_labels = []
    for batch, result in zip(batches, batch_results):
        if result is not None:
            all_labels.extend(result)
        else:
            for job in batch:
                with _fallback_lock:
                    _dir_fallbacks.append({
                        "title": job.get("title", ""),
                        "llm_direction": None,
                        "fallback_to": classify_job(job.get("title", ""), weight_rules),
                        "reason": "LLM批次调用失败",
                    })

    # ── 6. 校验与兜底 ──
    label_by_index = {}
    for label in all_labels:
        idx = label.get("index")
        if idx is not None:
            label_by_index[idx] = label

    for job in jobs:
        idx = job.get("index")
        llm_dir = None
        if idx in label_by_index:
            llm_dir = label_by_index[idx].get("direction", "")

        if llm_dir and llm_dir in valid_directions:
            job["llm_direction"] = llm_dir
            job["direction_source"] = "llm"
        else:
            fallback = classify_job(job.get("title", ""), weight_rules)
            job["llm_direction"] = fallback
            job["direction_source"] = "keyword_fallback"
            if llm_dir:
                emit(f"   ⚠️ 方向兜底: {job.get('title', '?')[:40]} LLM方向={llm_dir} 无效，回退为 {fallback}")
                with _fallback_lock:
                    _dir_fallbacks.append({"title": job.get("title", ""), "llm_direction": llm_dir, "fallback_to": fallback, "reason": "LLM方向无效"})
            else:
                emit(f"   ⚠️ 方向兜底: {job.get('title', '?')[:40]} LLM未返回方向，回退为 {fallback}")
                with _fallback_lock:
                    _dir_fallbacks.append({"title": job.get("title", ""), "llm_direction": None, "fallback_to": fallback, "reason": "LLM未返回方向"})

    return jobs


def _score_batch(batch, profile_summary, weights, batch_label="", strategy: str = None, config: dict = None):
    """对一批岗位调用 LLM 评分，返回 scored 列表（可能为空）。

    Args:
        strategy: 策略方向名（如 "web3"），用于加载对应的 few-shot 示例
        config: Campaign 配置字典，用于读取 JD 截断长度等参数
    """

    prompts = load_prompts()
    template = _load_scoring_prompt()
    system_prompt = render_prompt(template,
        profile_summary=profile_summary,
        weights_text=_build_weights_text(weights),
        score_formula=_build_score_formula(weights),
    )

    # 注入 few-shot 示例
    if strategy:
        examples_text = _load_scoring_examples(strategy)
        if examples_text:
            system_prompt += "\n\n" + examples_text

    jobs_text = ""
    for j, job in enumerate(batch, 1):
        jobs_text += f"\n--- 岗位 {j} ---\n"
        jobs_text += f"标题: {job.get('title', '未知')}\n"
        if job.get("company"):
            jobs_text += f"公司: {job['company']}\n"
        if job.get("location"):
            jobs_text += f"地点: {job['location']}\n"
        if job.get("salary"):
            jobs_text += f"薪资: {job['salary']}\n"
        desc = job.get("description", "")
        max_chars = (config or {}).get("search", {}).get("jd_max_chars", 4000)
        if len(desc) > max_chars:
            desc = desc[:max_chars] + "\n...(截断)"
        jobs_text += f"职位描述:\n{desc}\n"
        jobs_text += f"链接: {job.get('url', '')}\n"

    if DIAGNOSE_MODE:
        emit(f"   📤 [诊断] {batch_label}: 发送 {len(batch)} 个 JD，prompt {len(jobs_text)} 字符:\n{jobs_text}")

    try:
        # 主路径：Instructor + Pydantic 结构化输出
        from engine.contracts import MatchResult
        results = llm_call(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": jobs_text}],
            temperature=0, thinking={"type": "disabled"},
            response_model=list[MatchResult],
        )
        # Per-batch token 统计（线程安全：_store_usage 写入当前线程的 _usage_local）
        batch_input_tok, batch_output_tok = get_last_usage()
        raw_text = get_last_raw_response_text()

        scored = [m.model_dump() for m in results]
        if scored:
            emit(f"   📝 [诊断] {batch_label}: 解析 {len(scored)}/{len(batch)}, "
                 f"token in={batch_input_tok} out={batch_output_tok}, "
                 f"LLM原始返回 {len(raw_text)} 字符"
                 + (f":\n{raw_text}" if DIAGNOSE_MODE else ""))
            # 数量不匹配时额外警告
            if len(scored) < len(batch):
                emit(f"   ⚠️ [诊断] {batch_label}: 期望{len(batch)}个, 丢失eval_id: {[j.get('eval_id', '?') for j in batch[len(scored):]]}")
            return scored
        else:
            emit(f"   ⚠️ {batch_label}返回格式异常，跳过 (token in={batch_input_tok} out={batch_output_tok})")
            return []
    except Exception as e:
        # 失败时输出 prompt 上下文（截断）用于追溯问题批次
        prompt_preview = jobs_text[:800] + ("..." if len(jobs_text) > 800 else "")
        emit(f"   ❌ {batch_label}评分失败: {e}")
        emit(f"   📋 失败批次 prompt 前 800 字符:\n{prompt_preview}")
        # 不丢数据：为批次内每个 JD 返回一条标记了错误的记录
        error_scored = []
        for j, job in enumerate(batch, 1):
            error_scored.append({
                "index": j,
                "title": job.get("title", "未知"),
                "company": job.get("company", ""),
                "scores": {"skill": 0, "experience": 0, "level": 0, "industry": 0, "bonus": 0},
                "reason": f"LLM 评分调用失败，请重试: {str(e)[:150]}",
                "recommendation": "不推荐",
                "_score_error": True,
            })
        return error_scored


# ============================================================
#  岗位匹配分析（动态权重 + 及格线复评）
# ============================================================

def match_jobs(config: dict = None, profile: dict = None):
    """读取用户档案和最新岗位数据，用 LLM 做多维度匹配评分。

    Args:
        config: 配置字典（不传则从 search_config.yaml 加载）
        profile: 用户画像字典（不传则从 me.yaml 加载）
    """
    if profile is None:
        profile = load_profile()

    # 找到当前 run 目录中的岗位文件
    run_dir = get_current_run_dir() or get_latest_run_dir()
    if not run_dir:
        return "错误：还没有搜索过岗位，请先搜索"
    raw_path = os.path.join(run_dir, "raw_jobs.json")
    if not os.path.exists(raw_path):
        return "错误：没有找到岗位数据，请先搜索"

    with open(raw_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        return "岗位数据为空"

    if config is None:
        raise RuntimeError("match_jobs 需要 config 参数，请通过 Campaign 提供。CLI 使用 --campaign，Web UI 选择求职方向。")

    matching_cfg = config.get("matching", {})
    min_score = matching_cfg.get("min_match_score", 50)
    top_n = matching_cfg.get("top_n", 10)
    borderline_rescore = matching_cfg.get("borderline_rescore", False)
    borderline_range = matching_cfg.get("borderline_range", 8)
    weight_profiles = matching_cfg.get("weight_profiles", {})

    # ── 核心逻辑：纯函数调用 ──
    direction_results, all_scored = execute_matching_pipeline(jobs, profile, config)

    from config import get_accumulated_usage
    total_usage = get_accumulated_usage()

    # ── Step 1 结果独立落盘 ──
    direction_path = os.path.join(run_dir, "direction_results.json")
    with open(direction_path, "w", encoding="utf-8") as f:
        json.dump(direction_results, f, ensure_ascii=False, indent=2)
    track_file(direction_path, f"方向分类结果 JSON（{len(direction_results)} 个岗位）")

    # ── 对比 Step 1 和 Step 2，找出 LLM 漏评的岗位（用 URL 做唯一键）──
    scored_urls = {s["url"] for s in all_scored if s.get("url")}

    scoring_failed = []
    for dr in direction_results:
        url = dr.get("url", "")
        if url and url not in scored_urls:
            scoring_failed.append({
                "eval_id": dr.get("eval_id"),
                "title": dr.get("title", ""),
                "company": dr.get("company", ""),
                "url": url,
                "description": dr.get("description", ""),
                "llm_direction": dr.get("llm_direction", "default"),
                "weight_profile": dr.get("llm_direction", "default"),
                "scores": {"skill": 0, "experience": 0, "level": 0, "industry": 0, "bonus": 0},
                "total_score": -1,
                "reason": "LLM 评分漏返，未参与打分",
                "recommendation": "不推荐（评分异常）",
                "score_rounds": [],
                "score_variance": 0,
                "confidence": "failed",
                "skill_match": [],
                "missing_skills": [],
                "_score_missing": True,
            })

    if scoring_failed:
        emit(f"   ⚠️ LLM 漏评 {len(scoring_failed)} 个岗位，已标记 total_score=-1")

    # ── 过滤 ──
    qualified = [s for s in all_scored
                 if s.get("total_score", 0) >= min_score][:top_n]

    # 保存未达标岗位（低于 min_score 的）—— 先落盘，避免报告生成崩溃丢数据
    unmatched = [s for s in all_scored if s.get("total_score", 0) < min_score]
    if unmatched:
        unmatched_path = os.path.join(run_dir, "unmatched_jobs.json")
        with open(unmatched_path, "w", encoding="utf-8") as f:
            json.dump(unmatched, f, ensure_ascii=False, indent=2)
        track_file(unmatched_path, f"未达标岗位数据 JSON（{len(unmatched)} 个，低于 {min_score} 分）")

    # 保存匹配结果 JSON 到 run 目录
    matched_path = os.path.join(run_dir, "matched_jobs.json")
    with open(matched_path, "w", encoding="utf-8") as f:
        json.dump(qualified, f, ensure_ascii=False, indent=2)
    track_file(matched_path, f"匹配结果数据 JSON（{len(qualified)} 个岗位评分，供生成简历用）")

    # 保存兜底触发报告
    fallback_path = os.path.join(run_dir, "fallback_report.json")
    with open(fallback_path, "w", encoding="utf-8") as f:
        json.dump({
            "direction_fallbacks": {"count": len(_dir_fallbacks), "details": _dir_fallbacks},
            "weight_fallbacks": {"count": len(_weight_fallbacks), "details": _weight_fallbacks},
            "score_errors": {"count": len(_score_errors), "details": _score_errors},
        }, f, ensure_ascii=False, indent=2)
    track_file(fallback_path, f"兜底触发报告（方向{len(_dir_fallbacks)} 权重{len(_weight_fallbacks)} 评分{len(_score_errors)}）")

    if scoring_failed:
        failed_path = os.path.join(run_dir, "scoring_failed_jobs.json")
        with open(failed_path, "w", encoding="utf-8") as f:
            json.dump(scoring_failed, f, ensure_ascii=False, indent=2)
        track_file(failed_path, f"评分失败岗位 JSON（{len(scoring_failed)} 个，LLM 漏返）")

    # ── 生成报告（放在文件保存之后，这样即使报告生成崩溃也不丢核心数据）──
    report = f"# 岗位匹配报告\n\n"
    report += f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"- 分析岗位数: {len(jobs)}\n"
    report += f"- 达标岗位数（≥{min_score}分）: {len(qualified)}\n"
    report += f"- 评分模式: 动态权重 + {'及格线复评' if borderline_rescore else '单轮评分'}\n\n"

    # 权重说明
    report += "### 权重方案\n\n"
    report += "| 类型 | 技能 | 经验 | 职级 | 行业 | 加分 |\n"
    report += "|------|------|------|------|------|------|\n"
    for pname in weight_profiles:
        pw, _ = get_weights(pname, weight_profiles)
        report += f"| {pname} | {pw['skill']}% | {pw['experience']}% | {pw['level']}% | {pw['industry']}% | {pw['bonus']}% |\n"
    report += "\n"

    for rank, s in enumerate(qualified, 1):
        score = s.get("total_score", 0)
        emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        wp = s.get("weight_profile", "default")
        confidence = s.get("confidence", "high")
        conf_tag = ""
        if confidence == "verified":
            conf_tag = " ✅已复评"
        elif confidence == "uncertain":
            conf_tag = " ⚠️波动大"

        report += f"## {rank}. {emoji} {score}分 | {s.get('title', '未知')} [{wp}]{conf_tag}\n\n"
        if s.get("company"):
            report += f"- 公司: {s['company']}\n"
        report += f"- 链接: {s.get('url', '无')}\n"
        report += f"- 权重方案: {wp}\n"

        scores = s.get("scores", {})
        if scores:
            report += f"- 技能匹配: {scores.get('skill', '?')} | "
            report += f"经验匹配: {scores.get('experience', '?')} | "
            report += f"职级匹配: {scores.get('level', '?')} | "
            report += f"行业匹配: {scores.get('industry', '?')} | "
            report += f"加分项: {scores.get('bonus', '?')}\n"

        if len(s.get("score_rounds", [])) > 1:
            rounds = s["score_rounds"]
            report += f"- 复评: 第1轮 {rounds[0]} / 第2轮 {rounds[1]}（波动 {s.get('score_variance', 0)}）\n"

        if s.get("skill_match"):
            report += f"- 技能: {', '.join(str(x) if isinstance(x, dict) else x for x in s['skill_match'])}\n"
        if s.get("missing_skills"):
            report += f"- 缺失: {', '.join(str(x) if isinstance(x, dict) else x for x in s['missing_skills'])}\n"

        report += f"- 分析: {s.get('reason', '')}\n"
        report += f"- 建议: {s.get('recommendation', '')}\n\n"

    # ── 评分失败岗位提醒 ──
    if scoring_failed:
        report += f"\n---\n\n"
        report += f"## ⚠️ 以下 {len(scoring_failed)} 个岗位因 AI 评分异常未出分，请单独查看或重试\n\n"
        report += f"| # | 岗位 | 公司 | 方向 |\n"
        report += f"|---|------|------|------|\n"
        for i, sf in enumerate(scoring_failed, 1):
            report += f"| {i} | {sf.get('title', '未知')} | {sf.get('company', '-')} | {sf.get('llm_direction', '-')} |\n"
        report += f"\n详情见 scoring_failed_jobs.json\n\n"

    # 保存报告到 run 目录
    report_path = os.path.join(run_dir, "job_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    track_file(report_path, f"匹配分析报告 Markdown（{len(qualified)} 个达标岗位排名）")

    # 返回摘要
    rescore_count = sum(1 for s in qualified if len(s.get("score_rounds", [])) > 1)
    summary = f"✅ 匹配分析完成！\n"
    summary += f"   分析了 {len(jobs)} 个岗位，达标 {len(qualified)} 个"
    if scoring_failed:
        summary += f"，评分失败 {len(scoring_failed)} 个"
    summary += "\n"
    summary += f"   Token: 输入 {total_usage['input_tokens']:,} / 输出 {total_usage['output_tokens']:,}\n"
    summary += f"   评分模式: 动态权重 + {'及格线复评' if borderline_rescore else '单轮评分'}\n"
    if rescore_count:
        summary += f"   复评岗位: {rescore_count} 个（{min_score}±{borderline_range} 分区间）\n"
    summary += f"   报告: {os.path.basename(run_dir)}/job_report.md\n"
    summary += f"   匹配数据: {os.path.basename(run_dir)}/matched_jobs.json\n\n"
    for rank, s in enumerate(qualified[:8], 1):
        score = s.get("total_score", 0)
        emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        company_str = f" @ {s['company']}" if s.get("company") else ""
        wp = s.get("weight_profile", "default")
        conf = s.get("confidence", "high")
        conf_tag = " ✅复评" if conf == "verified" else " ⚠️波动" if conf == "uncertain" else ""
        summary += f"{rank}. {emoji} {score}分 [{wp}]{conf_tag} | {s.get('title', '未知')}{company_str}\n"
        if s.get("skill_match"):
            sm = s.get('skill_match', [])
            summary += f"   技能: {', '.join(str(x) if isinstance(x, dict) else x for x in sm[:6])}\n"
        summary += f"   {s.get('reason', '')}\n"
        summary += f"   {s.get('url', '')}\n\n"
    if len(qualified) > 8:
        summary += f"...完整排名见报告文件\n"

    return summary


# ============================================================
#  查看匹配结果
# ============================================================

def list_matched_jobs():
    """查看最近一次的匹配结果列表"""
    run_dir = get_current_run_dir() or get_latest_run_dir()
    if not run_dir:
        return "还没有搜索过岗位"

    matched_path = os.path.join(run_dir, "matched_jobs.json")
    if not os.path.exists(matched_path):
        return "还没有做过匹配分析，请先搜索并匹配"

    with open(matched_path, "r", encoding="utf-8") as f:
        matched = json.load(f)

    if not matched:
        return "匹配结果为空"

    output = f"📋 最近一次匹配结果（共 {len(matched)} 个达标岗位）：\n\n"
    for rank, s in enumerate(matched, 1):
        score = s.get("total_score", s.get("score", 0))
        emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        company_str = f" @ {s['company']}" if s.get("company") else ""
        wp = s.get("weight_profile", "")
        wp_str = f" [{wp}]" if wp and wp != "default" else ""
        conf = s.get("confidence", "")
        conf_str = " ✅复评" if conf == "verified" else " ⚠️波动" if conf == "uncertain" else ""
        output += f"{rank}. {emoji} {score}分{wp_str}{conf_str} | {s.get('title', '未知')}{company_str}\n"

        scores = s.get("scores", {})
        if scores:
            output += f"   [技能:{scores.get('skill', '?')} | 经验:{scores.get('experience', '?')} | "
            output += f"职级:{scores.get('level', '?')} | 行业:{scores.get('industry', '?')} | "
            output += f"加分:{scores.get('bonus', '?')}]\n"

        if len(s.get("score_rounds", [])) > 1:
            rounds = s["score_rounds"]
            output += f"   🔄 复评: {rounds[0]}→{rounds[1]}（波动 {s.get('score_variance', 0)}）\n"

        if s.get("missing_skills"):
            ms = s.get('missing_skills', [])
            output += f"   ⚠️ 缺失: {', '.join(str(x) if isinstance(x, dict) else x for x in ms)}\n"

        output += f"   {s.get('reason', '')}\n"
        output += f"   {s.get('url', '')}\n\n"

    output += "💡 输入「为第X个岗位生成简历」即可生成定制简历（含 HTML + PDF）"
    return output


# ============================================================
#  单条 JD 评分（供评估脚本使用）
# ============================================================

def _load_common_direction_examples() -> str:
    """加载公共方向分类 few-shot 示例（跨方向通用，仅加载一次）。"""
    import yaml as _yaml
    from pathlib import Path as _Path

    examples_dir = _Path(__file__).parent / "prompts" / "examples" / "job_match" / "direction"
    common_file = examples_dir / "common.yaml"
    if not common_file.exists():
        return ""

    with open(common_file, "r", encoding="utf-8") as f:
        data = _yaml.safe_load(f)

    lines = []
    for ex in data.get("examples", []):
        inp = ex.get("input", "").strip()
        out = ex.get("ideal_output", {})
        lines.append(
            f"示例：\n"
            f"  JD: {inp}\n"
            f"  正确方向: {out.get('direction', '')}\n"
            f"  理由: {out.get('reason', '')}"
        )

    if lines:
        return "===== 参考示例 =====\n\n" + "\n\n".join(lines)
    return ""


def _load_direction_examples(strategy: str) -> str:
    """根据方向名，加载该方向的专属 few-shot 示例。"""
    import yaml as _yaml
    from pathlib import Path as _Path

    examples_dir = _Path(__file__).parent / "prompts" / "examples" / "job_match" / "direction"
    direction_file = examples_dir / f"{strategy}.yaml"
    if not direction_file.exists():
        return ""

    with open(direction_file, "r", encoding="utf-8") as f:
        data = _yaml.safe_load(f)

    lines = []
    for ex in data.get("examples", []):
        inp = ex.get("input", "").strip()
        out = ex.get("ideal_output", {})
        lines.append(
            f"示例：\n"
            f"  JD: {inp}\n"
            f"  正确方向: {out.get('direction', '')}\n"
            f"  理由: {out.get('reason', '')}"
        )

    if lines:
        return "===== 参考示例 =====\n\n" + "\n\n".join(lines)
    return ""


def _load_scoring_examples(strategy: str) -> str:
    """根据当前策略方向，加载对应的评分 few-shot 示例。"""
    import yaml as _yaml
    from pathlib import Path as _Path

    examples_dir = _Path(__file__).parent / "prompts" / "examples" / "job_match" / "scoring"
    example_texts = []

    # 始终加载 common.yaml
    common_file = examples_dir / "common.yaml"
    if common_file.exists():
        with open(common_file, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        for ex in data.get("examples", []):
            inp = ex.get("input", "").strip()
            out = ex.get("ideal_output", {})
            example_texts.append(
                f"示例：\n"
                f"  JD: {inp}\n"
                f"  正确方向: {out.get('direction', '')}\n"
                f"  理由: {out.get('reason', '')}"
            )

    # 加载 strategy 对应的评分示例文件
    scoring_file = examples_dir / f"{strategy}.yaml"
    if scoring_file.exists():
        with open(scoring_file, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        for ex in data.get("examples", []):
            inp = ex.get("input", "").strip()
            out = ex.get("ideal_output", {})
            example_texts.append(
                f"示例：\n"
                f"  JD: {inp}\n"
                f"  正确方向: {out.get('direction', '')}\n"
                f"  理由: {out.get('reason', '')}"
            )

    if example_texts:
        return "===== 参考示例 =====\n\n" + "\n\n".join(example_texts)
    return ""


def _build_profile_summary(user_profile: dict) -> str:
    """从用户画像构造评分用 profile_summary。剔除薪资隐私，注入核心成就数据。"""
    # 剔除薪资隐私
    job_intent = dict(user_profile.get("job_intent", {}))
    job_intent.pop("salary_expectation", None)

    # 工作经历：保留现有字段 + 注入 key_achievements 的 resume_bullet
    work_exps = []
    for exp in user_profile.get("work_experience", []):
        ka_list = exp.get("key_achievements", [])
        work_exps.append({
            "title":        exp.get("title"),
            "company":      exp.get("company_en", exp.get("company", "")),
            "period":       exp.get("period", ""),
            "tech_stack":   exp.get("tech_stack", []),
            "highlights":   exp.get("highlights", []),
            "achievements": [
                ka.get("resume_bullet", [])
                for ka in ka_list
            ],
        })

    return json.dumps({
        "job_intent":      job_intent,
        "skills":          user_profile.get("skills", {}),
        "work_experience": work_exps,
        "projects": [
            {"name":           p.get("name"),
             "role":           p.get("role"),
             "tech_stack":     p.get("tech_stack", []),
             "resume_bullets": [rb.get("text", "") for rb in p.get("resume_bullets", [])]}
            for p in user_profile.get("projects", [])
        ],
        "education":       user_profile.get("education", []),
        "certifications":  user_profile.get("certifications", []),
        "summary":         user_profile.get("summary", "")
    }, ensure_ascii=False, indent=2)


def execute_matching_pipeline(jobs_list: list, profile: dict, config: dict) -> tuple[list, list]:
    """纯函数：对 job 列表执行方向分类 → 五维评分 → 及格线复评。

    不涉及任何文件读写、过滤、排序后处理。
    调用方负责准备 jobs_list 和解析返回结果。

    Args:
        jobs_list: job 字典列表，每条需含 title / description，
                   可选 company / url / location / salary / eval_id 等。
        profile: 用户画像字典。
        config: Campaign 配置字典。

    Returns:
        (direction_results, all_scored) 元组。

        - direction_results: 全量方向分类结果列表。
          每条：{eval_id, title, company, url, description, llm_direction, direction_source}。
          长度始终等于输入 jobs_list 的长度，是所有下游方向判断的权威数据源。

        - all_scored: 评分结果列表，按 total_score 降序排列。
          每条含 eval_id、title、scores、total_score、reason 等。
          LLM 漏返回时，此列表长度可能小于 direction_results。
    """
    global _dir_fallbacks, _weight_fallbacks, _score_errors
    with _fallback_lock:
        _dir_fallbacks.clear()
        _weight_fallbacks.clear()
        _score_errors.clear()

    from config import clear_usage_accumulator
    clear_usage_accumulator()

    if config is None:
        raise RuntimeError("execute_matching_pipeline 需要 config 参数")

    matching_cfg = config.get("matching", {})
    min_score = matching_cfg.get("min_match_score", 50)
    weight_profiles = matching_cfg.get("weight_profiles", {
        "default": {"skill": 30, "experience": 25, "level": 15, "industry": 15, "bonus": 15}
    })
    weight_rules = matching_cfg.get("weight_rules", {})
    borderline_rescore = matching_cfg.get("borderline_rescore", False)
    borderline_range = matching_cfg.get("borderline_range", 8)
    batch_size = matching_cfg.get("score_batch_size", 5)
    rescore_batch_size = matching_cfg.get("rescore_batch_size", 5)

    # ── B.1: 构建 profile_summary ──
    profile_summary = _build_profile_summary(profile)

    # ── B.2: 方向分类 ──
    emit(f"\n{'='*50}")
    emit(f"🏷️ Step 1: 方向分类（LLM 预判）")
    emit(f"{'='*50}")
    jobs = classify_direction_batch(jobs_list, config)

    # ── 构建全量方向结果（独立于评分链路，作为方向的权威数据源）──
    direction_results = []
    for j in jobs:
        direction_results.append({
            "eval_id": j.get("eval_id"),
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "url": j.get("url", ""),
            "description": j.get("description", ""),
            "llm_direction": j.get("llm_direction", "default"),
            "direction_source": j.get("direction_source", "unknown"),
        })

    dir_counts = {}
    for j in jobs:
        d = j.get("llm_direction", "default")
        dir_counts[d] = dir_counts.get(d, 0) + 1
    dir_summary = ", ".join(f"{d}: {c}" for d, c in sorted(dir_counts.items()))
    emit(f"   方向分布: {dir_summary}")

    # ── B.3: 按方向分批评分（并发模式）──
    emit(f"\n{'='*50}")
    emit(f"📊 Step 2: 按方向分批评分（并发模式）")
    emit(f"{'='*50}")

    jobs_by_direction = {}
    for j in jobs:
        d = j.get("llm_direction", "default")
        jobs_by_direction.setdefault(d, []).append(j)

    # 1. 扁平化：将所有「方向 × 批次」展开为独立任务
    all_scoring_tasks = []  # [(direction, batch, local_batch, weights, batch_label), ...]

    for direction, dir_jobs in jobs_by_direction.items():
        dir_weights, weight_source = get_weights(direction, weight_profiles)
        emit(f"\n   📂 {direction} 方向（{len(dir_jobs)} 个岗位）")
        emit(f"   🎯 权重: 技能{dir_weights['skill']}% 经验{dir_weights['experience']}% "
             f"职级{dir_weights['level']}% 行业{dir_weights['industry']}% 加分{dir_weights['bonus']}% "
             f"(来源: {weight_source})")
        if "代码默认值" in weight_source:
            with _fallback_lock:
                _weight_fallbacks.append({"direction": direction, "weight_profile": weight_source})

        for i in range(0, len(dir_jobs), batch_size):
            batch = dir_jobs[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(dir_jobs) + batch_size - 1) // batch_size

            local_batch = []
            for local_idx, job in enumerate(batch, 1):
                temp_job = job.copy()
                temp_job["index"] = local_idx
                local_batch.append(temp_job)

            all_scoring_tasks.append({
                "direction": direction,
                "batch": batch,
                "local_batch": local_batch,
                "weights": dir_weights,
                "batch_label": f"{direction} 第 {batch_num}/{total_batches} 批",
            })

    # 2. 构建所有 thunk
    def _make_scoring_thunk(task):
        def _run():
            scored = _score_batch(
                task["local_batch"], profile_summary, task["weights"],
                batch_label=task["batch_label"],
                strategy=task["direction"], config=config,
            )
            return scored, task
        return _run

    thunks = [_make_scoring_thunk(t) for t in all_scoring_tasks]

    # 3. 并发执行
    concurrency = get_llm_concurrency()
    batch_results = run_batches_concurrently(
        thunks,
        max_workers=min(concurrency, len(thunks)) if thunks else 1,
        description="评分",
    )

    # 4. 合并 + 后处理
    all_scored = []

    for batch_result in batch_results:
        if batch_result is None:
            continue
        scored, task = batch_result

        # 诊断
        if len(scored) < len(task["batch"]):
            matched_ids = set()
            for pos, s in enumerate(scored):
                if pos < len(task["batch"]):
                    matched_ids.add(task["batch"][pos].get("eval_id", "?"))
            all_ids = [j.get("eval_id", "?") for j in task["batch"]]
            missing = [eid for eid in all_ids if eid not in matched_ids]
            emit(f"   ⚠️ [诊断] {task['batch_label']}: 输入{len(task['batch'])}个 → LLM返回{len(scored)}个，丢失eval_id: {missing}")

        # 按位置匹配 + 字段补全
        for pos, s in enumerate(scored):
            if pos < len(task["batch"]):
                orig_job = task["batch"][pos]
                s["url"] = orig_job.get("url", "")
                s["description"] = orig_job.get("description", "")
                if not s.get("title"):
                    s["title"] = orig_job.get("title", "")
                if not s.get("company"):
                    s["company"] = orig_job.get("company", "")
                s["weight_profile"] = orig_job.get("llm_direction", "default")
                s["index"] = orig_job.get("index")
                if orig_job.get("eval_id"):
                    s["eval_id"] = orig_job["eval_id"]

            if s.get("scores"):
                s["total_score"] = _calc_total_score(s["scores"], task["weights"])
                s["level_tier"] = _determine_level_by_discrete_scores(s["scores"])
            s["score_rounds"] = [s.get("total_score", 0)]
            s["score_variance"] = 0
            s["confidence"] = "high"

        all_scored.extend(scored)

        for s in scored:
            if s.get("_score_error"):
                with _fallback_lock:
                    _score_errors.append({"title": s.get("title", "未知"), "reason": s.get("reason", "")})

        # ── 定向重试漏评岗位（串行，仅在漏评时触发）──
        if len(scored) < len(task["batch"]):
            missed = task["batch"][len(scored):]
            emit(f"   🔄 定向重试 {len(missed)} 个漏评岗位（单条独立）: {[j.get('eval_id', j.get('title', '?')[:30]) for j in missed]}")

            for job in missed:
                single = [job.copy()]
                single[0]["index"] = 1
                retry_result = _score_batch(single, profile_summary, task["weights"],
                                            batch_label=f"{task['direction']} 单条重试",
                                            strategy=task["direction"], config=config)
                if retry_result and len(retry_result) == 1:
                    s = retry_result[0]
                    s["url"] = job.get("url", "")
                    s["description"] = job.get("description", "")
                    if not s.get("title"):
                        s["title"] = job.get("title", "")
                    if not s.get("company"):
                        s["company"] = job.get("company", "")
                    s["weight_profile"] = job.get("llm_direction", "default")
                    s["index"] = job.get("index")
                    if job.get("eval_id"):
                        s["eval_id"] = job["eval_id"]
                    if s.get("scores"):
                        s["total_score"] = _calc_total_score(s["scores"], task["weights"])
                        s["level_tier"] = _determine_level_by_discrete_scores(s["scores"])
                    s["score_rounds"] = [s.get("total_score", 0)]
                    s["score_variance"] = 0
                    s["confidence"] = "high"
                    all_scored.append(s)
                    if s.get("_score_error"):
                        with _fallback_lock:
                            _score_errors.append({"title": s.get("title", "未知"), "reason": s.get("reason", "")})
                else:
                    emit(f"   ⚠️ 重试后仍失败: {job.get('eval_id', job.get('title', '?')[:30])}")

    # ── B.4: 排序 ──
    all_scored.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    # ── B.5: 及格线复评 ──
    if borderline_rescore:
        low = min_score - borderline_range
        high = min_score + borderline_range
        borderline_jobs = [s for s in all_scored if low <= s.get("total_score", 0) <= high]

        if borderline_jobs:
            emit(f"\n   🔄 及格线复评：{len(borderline_jobs)} 个岗位处于 {low}-{high} 分区间...")

            url_to_job = {normalize_jobsdb_url(j.get("url", "")): j for j in jobs}

            rescore_groups = {}
            for s in borderline_jobs:
                d = s.get("llm_direction", "default")
                rescore_groups.setdefault(d, []).append(s)

            for direction, dir_jobs in rescore_groups.items():
                dir_weights, ws = get_weights(direction, weight_profiles)
                if "代码默认值" in ws:
                    with _fallback_lock:
                        _weight_fallbacks.append({"direction": direction, "weight_profile": ws})

                for i in range(0, len(dir_jobs), rescore_batch_size):
                    batch = dir_jobs[i:i + rescore_batch_size]
                    # 构建 original_batch：用 url 查找原始 job，找不到则用 scored 对象自身
                    original_batch = []
                    for s in batch:
                        norm = normalize_jobsdb_url(s.get("url", ""))
                        orig = url_to_job.get(norm)
                        if orig:
                            original_batch.append(orig)
                        else:
                            original_batch.append({
                                "title": s.get("title", ""),
                                "company": s.get("company", ""),
                                "description": s.get("description", ""),
                                "url": s.get("url", ""),
                                "eval_id": s.get("eval_id", ""),
                                "index": s.get("index"),
                            })

                    # 构建 local_batch 给 LLM（局部 index 1-N）
                    local_batch = []
                    for local_idx, job in enumerate(original_batch, 1):
                        temp_job = job.copy()
                        temp_job["index"] = local_idx
                        local_batch.append(temp_job)

                    batch_num = i // rescore_batch_size + 1
                    total_batches = (len(dir_jobs) + rescore_batch_size - 1) // rescore_batch_size
                    scored2_list = _score_batch(local_batch, profile_summary, dir_weights,
                                                batch_label=f"复评 {direction} 第 {batch_num}/{total_batches} 批",
                                                strategy=direction, config=config)

                    # 诊断：检查复评 LLM 返回数量是否与输入一致
                    if len(scored2_list) < len(batch):
                        missing = [batch[pos].get("eval_id", "?") for pos in range(len(scored2_list), len(batch))]
                        emit(f"   ⚠️ [诊断] 复评{direction} 第{batch_num}批: 输入{len(batch)}个 → LLM返回{len(scored2_list)}个，丢失eval_id: {missing}")

                    # 按位置匹配复评结果
                    for pos, s in enumerate(batch):
                        if pos < len(scored2_list):
                            s2 = scored2_list[pos]
                            if s2.get("scores"):
                                round2_total = _calc_total_score(s2["scores"], dir_weights)
                                round1_total = s["score_rounds"][0]
                                avg_scores = {}
                                for dim in ["skill", "experience", "level", "industry", "bonus"]:
                                    avg_scores[dim] = round(
                                        (s.get("scores", {}).get(dim, 0) + s2["scores"].get(dim, 0)) / 2
                                    )
                                avg_total = _calc_total_score(avg_scores, dir_weights)
                                variance = abs(round1_total - round2_total)

                                s["scores"] = avg_scores
                                s["total_score"] = avg_total
                                s["level_tier"] = _determine_level_by_discrete_scores(avg_scores)
                                s["score_rounds"] = [round1_total, round2_total]
                                s["score_variance"] = variance
                                s["confidence"] = "verified" if variance <= 10 else "uncertain"

                                if variance > 10:
                                    s["reason"] = f"⚠️ 评分波动较大（{round1_total} vs {round2_total}）| " + s.get("reason", "")

                            emit(f"     📊 {s.get('title', '?')[:35]}: "
                                 f"{round1_total}→{round2_total}（平均 {avg_total}，波动 {variance}）")

            all_scored.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    return direction_results, all_scored
