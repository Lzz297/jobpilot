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
)
from scraper import normalize_jobsdb_url


# ── 模块级兜底记录列表（match_jobs() 开始时清空，被 classify_direction_batch / _score_batch 等追加）──
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
    """根据权重手动计算加权总分（四舍五入取整）。"""
    return round(
        scores.get("skill", 0) * weights["skill"] / 100 +
        scores.get("experience", 0) * weights["experience"] / 100 +
        scores.get("level", 0) * weights["level"] / 100 +
        scores.get("industry", 0) * weights["industry"] / 100 +
        scores.get("bonus", 0) * weights["bonus"] / 100
    )


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

    # 注入方向分类 few-shot 示例（每个方向单独加载）
    for dir_name in direction_names:
        examples_text = _load_direction_examples(dir_name)
        if examples_text:
            system_prompt += "\n\n" + examples_text

    # ── 3. 分批调用 LLM ──
    # direction_batch_size: 将来可暴露到 Web UI
    direction_batch_size = (config or {}).get("matching", {}).get("direction_batch_size", 20)
    jd_max_chars = (config or {}).get("search", {}).get("jd_max_chars", 4000)
    valid_directions = set(weight_rules.keys()) | {"default"}

    all_labels = []

    for i in range(0, len(jobs), direction_batch_size):
        batch = jobs[i:i + direction_batch_size]
        batch_num = i // direction_batch_size + 1
        total_batches = (len(jobs) + direction_batch_size - 1) // direction_batch_size

        emit(f"   🏷️ 方向分类 第 {batch_num}/{total_batches} 批（{len(batch)} 个岗位）...")

        # 构造 user message
        jobs_text = ""
        for j, job in enumerate(batch):
            job_idx = job.get("index", i + j + 1)
            jobs_text += f"\n--- 岗位 {job_idx} ---\n"
            jobs_text += f"标题: {job.get('title', '未知')}\n"
            if job.get("company"):
                jobs_text += f"公司: {job['company']}\n"
            desc = job.get("description", "")
            if len(desc) > jd_max_chars:
                desc = desc[:jd_max_chars] + "\n...(截断)"
            jobs_text += f"职位描述:\n{desc}\n"

        try:
            # 主路径：Instructor + Pydantic 结构化输出
            from engine.contracts import DirectionLabel
            results = llm_call(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": jobs_text}],
                temperature=0, thinking={"type": "disabled"},
                response_model=list[DirectionLabel],
            )
            labels = [m.model_dump() for m in results]
            all_labels.extend(labels)
        except Exception as e:
            emit(f"   ❌ 方向分类第 {batch_num} 批失败: {e}")
            for job in batch:
                _dir_fallbacks.append({"title": job.get("title", ""), "llm_direction": None, "fallback_to": classify_job(job.get("title", ""), weight_rules), "reason": "LLM批次调用失败"})

    # ── 4. 校验与兜底 ──
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
        else:
            fallback = classify_job(job.get("title", ""), weight_rules)
            job["llm_direction"] = fallback
            if llm_dir:
                emit(f"   ⚠️ 方向兜底: {job.get('title', '?')[:40]} LLM方向={llm_dir} 无效，回退为 {fallback}")
                _dir_fallbacks.append({"title": job.get("title", ""), "llm_direction": llm_dir, "fallback_to": fallback, "reason": "LLM方向无效"})
            else:
                emit(f"   ⚠️ 方向兜底: {job.get('title', '?')[:40]} LLM未返回方向，回退为 {fallback}")
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

    try:
        # 主路径：Instructor + Pydantic 结构化输出
        from engine.contracts import MatchResult
        results = llm_call(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": jobs_text}],
            temperature=0, thinking={"type": "disabled"},
            response_model=list[MatchResult],
        )
        scored = [m.model_dump() for m in results]
        if scored:
            return scored
        else:
            emit(f"   ⚠️ {batch_label}返回格式异常，跳过")
            return []
    except Exception as e:
        emit(f"   ❌ {batch_label}评分失败: {e}")
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
    global _dir_fallbacks, _weight_fallbacks, _score_errors
    _dir_fallbacks = []
    _weight_fallbacks = []
    _score_errors = []

    # 加载用户档案
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

    # 加载匹配配置
    if config is None:
        raise RuntimeError("match_jobs 需要 config 参数，请通过 Campaign 提供。CLI 使用 --campaign，Web UI 选择求职方向。")
    matching_cfg = config.get("matching", {})
    min_score = matching_cfg.get("min_match_score", 50)
    top_n = matching_cfg.get("top_n", 10)

    # 动态权重配置
    weight_profiles = matching_cfg.get("weight_profiles", {"default": {"skill": 30, "experience": 25, "level": 15, "industry": 15, "bonus": 15}})
    weight_rules = matching_cfg.get("weight_rules", {})

    # 及格线复评配置
    borderline_rescore = matching_cfg.get("borderline_rescore", False)
    borderline_range = matching_cfg.get("borderline_range", 8)

    # 精简版用户信息
    profile_summary = json.dumps({
        "job_intent": profile.get("job_intent", {}),
        "skills": profile.get("skills", {}),
        "work_experience": [
            {"title": exp.get("title"), "company": exp.get("company_en", exp.get("company", "")),
             "period": exp.get("period", ""), "tech_stack": exp.get("tech_stack", []),
             "highlights": exp.get("highlights", [])}
            for exp in profile.get("work_experience", [])
        ],
        "education": profile.get("education", []),
        "certifications": profile.get("certifications", []),
        "summary": profile.get("summary", "")
    }, ensure_ascii=False, indent=2)

    # ── [新] Step 1: 独立的 LLM 方向预判 ──
    emit(f"\n{'='*50}")
    emit(f"🏷️ Step 1: 方向分类（LLM 预判）")
    emit(f"{'='*50}")
    jobs = classify_direction_batch(jobs, config)

    # 按方向分组统计
    dir_counts = {}
    for j in jobs:
        d = j.get("llm_direction", "default")
        dir_counts[d] = dir_counts.get(d, 0) + 1
    dir_summary = ", ".join(f"{d}: {c}" for d, c in sorted(dir_counts.items()))
    emit(f"   方向分布: {dir_summary}")

    # ── Step 2: 按方向分批评分（每组用各自的方向权重）──
    emit(f"\n{'='*50}")
    emit(f"📊 Step 2: 按方向分批评分")
    emit(f"{'='*50}")

    batch_size = matching_cfg.get("score_batch_size", 5)
    rescore_batch_size = matching_cfg.get("rescore_batch_size", 5)
    all_scored = []

    # 按 llm_direction 分组
    jobs_by_direction = {}
    for j in jobs:
        d = j.get("llm_direction", "default")
        jobs_by_direction.setdefault(d, []).append(j)

    for direction, dir_jobs in jobs_by_direction.items():
        dir_weights, weight_source = get_weights(direction, weight_profiles)
        emit(f"\n   📂 {direction} 方向（{len(dir_jobs)} 个岗位）")
        emit(f"   🎯 方向 [{direction}] 权重: 技能{dir_weights['skill']}% 经验{dir_weights['experience']}% 职级{dir_weights['level']}% 行业{dir_weights['industry']}% 加分{dir_weights['bonus']}% (来源: {weight_source})")
        if "代码默认值" in weight_source:
            _weight_fallbacks.append({"direction": direction, "weight_profile": weight_source})

        for i in range(0, len(dir_jobs), batch_size):
            batch = dir_jobs[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(dir_jobs) + batch_size - 1) // batch_size

            emit(f"   📊 {direction} 第 {batch_num}/{total_batches} 批（{len(batch)} 个岗位）...")

            scored = _score_batch(batch, profile_summary, dir_weights,
                                  batch_label=f"{direction} 第 {batch_num} 批",
                                  strategy=direction, config=config)

            for s in scored:
                local_idx = s.get("index", 1) - 1
                if 0 <= local_idx < len(batch):
                    s["url"] = batch[local_idx].get("url", "")
                    s["description"] = batch[local_idx].get("description", "")
                    if not s.get("title"):
                        s["title"] = batch[local_idx].get("title", "")
                    if not s.get("company"):
                        s["company"] = batch[local_idx].get("company", "")
                    # 方向直接从 JD 数据读取（已在 classify_direction_batch 中确定）
                    s["llm_direction"] = batch[local_idx].get("llm_direction", "default")
                    s["weight_profile"] = s["llm_direction"]
                    # 用该方向权重计算 total_score
                    if s.get("scores"):
                        s["total_score"] = _calc_total_score(s["scores"], dir_weights)
                    s["score_rounds"] = [s.get("total_score", 0)]
                    s["score_variance"] = 0
                    s["confidence"] = "high"

            all_scored.extend(scored)
            for s in scored:
                if s.get("_score_error"):
                    _score_errors.append({"title": s.get("title", "未知"), "reason": s.get("reason", "")})

    # 排序
    all_scored.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    # ── 第二轮：及格线附近复评 ──
    if borderline_rescore:
        low = min_score - borderline_range
        high = min_score + borderline_range
        borderline_jobs = [s for s in all_scored if low <= s.get("total_score", 0) <= high]

        if borderline_jobs:
            emit(f"\n   🔄 及格线复评：{len(borderline_jobs)} 个岗位处于 {low}-{high} 分区间，进行二次评分...")

            # 需要从原始 jobs 中找到对应的 job 数据
            url_to_job = {normalize_jobsdb_url(j.get("url", "")): j for j in jobs}

            # 按方向分组
            rescore_groups = {}
            for s in borderline_jobs:
                d = s.get("llm_direction", "default")
                rescore_groups.setdefault(d, []).append(s)

            for direction, dir_jobs in rescore_groups.items():
                dir_weights, ws = get_weights(direction, weight_profiles)
                if "代码默认值" in ws:
                    _weight_fallbacks.append({"direction": direction, "weight_profile": ws})

                for i in range(0, len(dir_jobs), rescore_batch_size):
                    batch = dir_jobs[i:i + rescore_batch_size]
                    # 还原原始 job 数据用于重新评分
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
                            })

                    batch_num = i // rescore_batch_size + 1
                    total_batches = (len(dir_jobs) + rescore_batch_size - 1) // rescore_batch_size
                    batch_label = f"复评 {direction} 第 {batch_num}/{total_batches} 批"
                    scored2_list = _score_batch(original_batch, profile_summary, dir_weights,
                                                batch_label=batch_label, strategy=direction, config=config)

                    # 建立 scored2 的 index→结果 映射（index 从 1 开始）
                    scored2_map = {s2.get("index", 1) - 1: s2 for s2 in scored2_list}

                    for j, s in enumerate(batch):
                        s2 = scored2_map.get(j)
                        if s2 and s2.get("scores"):
                            round2_total = _calc_total_score(s2["scores"], dir_weights)
                            round1_total = s["score_rounds"][0]
                            # 取两轮平均
                            avg_scores = {}
                            for dim in ["skill", "experience", "level", "industry", "bonus"]:
                                avg_scores[dim] = round(
                                    (s.get("scores", {}).get(dim, 0) + s2["scores"].get(dim, 0)) / 2
                                )
                            avg_total = _calc_total_score(avg_scores, dir_weights)
                            variance = abs(round1_total - round2_total)

                            s["scores"] = avg_scores
                            s["total_score"] = avg_total
                            s["score_rounds"] = [round1_total, round2_total]
                            s["score_variance"] = variance
                            s["confidence"] = "verified" if variance <= 10 else "uncertain"

                            if variance > 10:
                                s["reason"] = f"⚠️ 评分波动较大（{round1_total} vs {round2_total}）| " + s.get("reason", "")

                            emit(f"     📊 {s.get('title', '?')[:35]}: "
                                  f"{round1_total}→{round2_total}（平均 {avg_total}，波动 {variance}）")

            # 复评后重新排序
            all_scored.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    qualified = [s for s in all_scored
                 if s.get("total_score", 0) >= min_score][:top_n]

    # ── 生成报告 ──
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
            report += f"- 技能: {', '.join(s['skill_match'])}\n"
        if s.get("missing_skills"):
            report += f"- 缺失: {', '.join(s['missing_skills'])}\n"

        report += f"- 分析: {s.get('reason', '')}\n"
        report += f"- 建议: {s.get('recommendation', '')}\n\n"

    # 保存报告到 run 目录
    report_path = os.path.join(run_dir, "job_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    track_file(report_path, f"匹配分析报告 Markdown（{len(qualified)} 个达标岗位排名）")

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

    # 保存未达标岗位（低于 min_score 的）
    unmatched = [s for s in all_scored if s.get("total_score", 0) < min_score]
    if unmatched:
        unmatched_path = os.path.join(run_dir, "unmatched_jobs.json")
        with open(unmatched_path, "w", encoding="utf-8") as f:
            json.dump(unmatched, f, ensure_ascii=False, indent=2)
        track_file(unmatched_path, f"未达标岗位数据 JSON（{len(unmatched)} 个，低于 {min_score} 分）")

    # 返回摘要
    rescore_count = sum(1 for s in qualified if len(s.get("score_rounds", [])) > 1)
    summary = f"✅ 匹配分析完成！\n"
    summary += f"   分析了 {len(jobs)} 个岗位，达标 {len(qualified)} 个\n"
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
            summary += f"   技能: {', '.join(s['skill_match'][:6])}\n"
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
            output += f"   ⚠️ 缺失: {', '.join(s['missing_skills'])}\n"

        output += f"   {s.get('reason', '')}\n"
        output += f"   {s.get('url', '')}\n\n"

    output += "💡 输入「为第X个岗位生成简历」即可生成定制简历（含 HTML + PDF）"
    return output


# ============================================================
#  单条 JD 评分（供评估脚本使用）
# ============================================================

def _load_direction_examples(strategy: str) -> str:
    """根据当前策略方向，加载对应的方向分类 few-shot 示例。"""
    import yaml as _yaml
    from pathlib import Path as _Path

    examples_dir = _Path(__file__).parent / "prompts" / "examples" / "job_match" / "direction"
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

    # 加载 strategy 对应的方向文件
    direction_file = examples_dir / f"{strategy}.yaml"
    if direction_file.exists():
        with open(direction_file, "r", encoding="utf-8") as f:
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
    """从用户画像构造 profile_summary（与 match_jobs 中的逻辑一致）。"""
    return json.dumps({
        "job_intent": user_profile.get("job_intent", {}),
        "skills": user_profile.get("skills", {}),
        "work_experience": [
            {"title": exp.get("title"), "company": exp.get("company_en", exp.get("company", "")),
             "period": exp.get("period", ""), "tech_stack": exp.get("tech_stack", []),
             "highlights": exp.get("highlights", [])}
            for exp in user_profile.get("work_experience", [])
        ],
        "education": user_profile.get("education", []),
        "certifications": user_profile.get("certifications", []),
        "summary": user_profile.get("summary", "")
    }, ensure_ascii=False, indent=2)


def score_single_jd(jd_text: str, user_profile: dict, config: dict = None,
                    jd_title: str = "") -> dict:
    """对单条 JD 进行方向预判 + 五维匹配评分。

    内部全部复用 Pipeline 的核心函数：classify_direction_batch + _score_batch。
    与 match_jobs 走完全相同的代码路径，确保评估结果反映线上实际表现。
    """
    if config is None:
        raise RuntimeError("score_single_jd 需要 config 参数，请从 Campaign 提供。")

    # ── Step 1: 方向预判（复用 classify_direction_batch）──
    job = {
        "title": jd_title or "未知岗位",
        "description": jd_text,
        "index": 1,
        "url": "",
        "company": "",
    }
    jobs = classify_direction_batch([job], config)
    direction = jobs[0].get("llm_direction", "default")

    # ── Step 2: 获取该方向权重 ──
    matching_cfg = config.get("matching", {})
    weight_profiles = matching_cfg.get("weight_profiles", {})
    dir_weights, _ = get_weights(direction, weight_profiles)

    # ── Step 3: 评分（复用 _score_batch）──
    profile_summary = _build_profile_summary(user_profile)
    scored_list = _score_batch(
        [job], profile_summary, dir_weights,
        batch_label=f"评估 {jd_title[:30]}" if jd_title else "评估",
        strategy=direction,
        config=config,
    )

    # ── Step 4: 组装返回 ──
    if scored_list:
        s = scored_list[0]
        scores = s.get("scores", {})
        reason = s.get("reason", "")
        total_score = _calc_total_score(scores, dir_weights) if scores else 0
    else:
        scores = {}
        total_score = 0
        reason = "LLM 评分调用失败"

    return {
        "direction": direction,
        "scores": scores,
        "total_score": total_score,
        "reason": reason,
    }
