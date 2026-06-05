"""
job_match.py - LLM 多维度匹配评分 + 结果查看
"""
import os
import json
import yaml
from datetime import datetime

from config import (
    emit, llm_call, OUTPUT_DIR, track_file,
    load_profile, load_search_config_dict, parse_json_response,
    get_current_run_dir, get_latest_run_dir, load_prompts, render_prompt,
)
from scraper import normalize_jobsdb_url


# ============================================================
#  岗位分类 & 动态权重
# ============================================================

_DEFAULT_WEIGHTS = {"skill": 30, "experience": 25, "level": 15, "industry": 15, "bonus": 15}

# 分类检查顺序：更具体的类别在前，通用类别在后
_CLASSIFY_ORDER = ["payment", "solutions", "web3", "technical"]


def classify_job(title, weight_rules):
    """根据岗位标题关键词匹配权重类型。按 _CLASSIFY_ORDER 优先级逐类检查。"""
    title_lower = title.lower()
    for category in _CLASSIFY_ORDER:
        keywords = weight_rules.get(category, [])
        for kw in keywords:
            if kw.lower() in title_lower:
                return category
    return "default"


def get_weights(profile_name, weight_profiles):
    """获取指定类型的权重字典，找不到则返回默认。"""
    return weight_profiles.get(profile_name, _DEFAULT_WEIGHTS)


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

_SCORING_SYSTEM_PROMPT = """你是一个专业求职顾问。根据候选人档案，对每个岗位从多个维度做匹配评分。

候选人档案：
<profile_summary>

请对每个岗位从以下5个维度打分（0-100），并计算加权总分：
<weights_text>

输出严格的 JSON 数组，不要输出其他任何文字：
[
  {
    "index": 岗位编号,
    "title": "岗位标题",
    "company": "公司名称",
    "direction": "payment/solutions/web3/technical/default",
    "scores": {
      "skill": 85,
      "experience": 90,
      "level": 80,
      "industry": 75,
      "bonus": 90
    },
    "total_score": 84,
    "skill_match": ["Python ✅", "FastAPI ✅", "Go ❌"],
    "missing_skills": ["Go"],
    "reason": "一段具体的匹配分析说明",
    "recommendation": "强烈推荐/推荐/考虑/不推荐"
  }
]

注意：
- total_score = <score_formula>（四舍五入取整）
- 如果 JD 内容不完整或过于笼统，在 reason 中注明并适当降低置信度
- skill_match 用 ✅❌⚠️ 标注每个关键技能"""


def _score_batch(batch, profile_summary, weights, batch_label=""):
    """对一批岗位调用 LLM 评分，返回 scored 列表（可能为空）。"""

    prompts = load_prompts()
    template = prompts.get("job_match", {}).get("scoring_system_prompt", _SCORING_SYSTEM_PROMPT)
    system_prompt = render_prompt(template,
        profile_summary=profile_summary,
        weights_text=_build_weights_text(weights),
        score_formula=_build_score_formula(weights),
    )

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
        if len(desc) > 3000:
            desc = desc[:3000] + "\n...(截断)"
        jobs_text += f"职位描述:\n{desc}\n"
        jobs_text += f"链接: {job.get('url', '')}\n"

    try:
        msg = llm_call(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": jobs_text}],
            temperature=0, thinking={"type": "disabled"},
        )
        result_text = msg.content
        scored = parse_json_response(result_text)
        if scored and isinstance(scored, list):
            return scored
        else:
            emit(f"   ⚠️ {batch_label}返回格式异常，跳过")
            return []
    except Exception as e:
        emit(f"   ❌ {batch_label}分析失败: {e}")
        return []


# ============================================================
#  岗位匹配分析（动态权重 + 及格线复评）
# ============================================================

def match_jobs():
    """读取用户档案和最新岗位数据，用 LLM 做多维度匹配评分"""
    # 加载用户档案
    profile, err = load_profile()
    if err:
        return err

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
    config, _ = load_search_config_dict()
    config = config or {}
    matching_cfg = config.get("matching", {})
    min_score = matching_cfg.get("min_match_score", 50)
    top_n = matching_cfg.get("top_n", 10)

    # 动态权重配置
    weight_profiles = matching_cfg.get("weight_profiles", {"default": _DEFAULT_WEIGHTS})
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

    # ── 第一轮：分批评分（统一用 default 权重，评完后按 LLM 方向重算） ──
    batch_size = 5
    all_scored = []
    default_weights = get_weights("default", weight_profiles)

    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(jobs) + batch_size - 1) // batch_size

        emit(f"   📊 分析第 {batch_num}/{total_batches} 批（{len(batch)} 个岗位）...")

        scored = _score_batch(batch, profile_summary, default_weights,
                              batch_label=f"第 {batch_num} 批")

        for s in scored:
            local_idx = s.get("index", 1) - 1
            if 0 <= local_idx < len(batch):
                s["url"] = batch[local_idx].get("url", "")
                s["description"] = batch[local_idx].get("description", "")
                if not s.get("title"):
                    s["title"] = batch[local_idx].get("title", "")
                if not s.get("company"):
                    s["company"] = batch[local_idx].get("company", "")
                # LLM 判断的方向（用于权重选择和简历聚合）
                llm_dir = s.get("direction", "")
                valid_directions = {"payment", "solutions", "web3", "technical", "default"}
                fallback_cat = classify_job(batch[local_idx].get("title", ""), weight_rules)
                s["llm_direction"] = llm_dir if llm_dir in valid_directions else fallback_cat
                s["weight_profile"] = s["llm_direction"]
                # 用 LLM 判断的方向对应的权重计算 total_score
                direction_weights = get_weights(s["llm_direction"], weight_profiles)
                if s.get("scores"):
                    s["total_score"] = _calc_total_score(s["scores"], direction_weights)
                s["score_rounds"] = [s.get("total_score", 0)]
                s["score_variance"] = 0
                s["confidence"] = "high"

        all_scored.extend(scored)

    # 排序
    all_scored.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    # 按 Job ID 去重
    seen_job_ids = set()
    deduped_scored = []
    for s in all_scored:
        norm = normalize_jobsdb_url(s.get("url", ""))
        if norm not in seen_job_ids:
            seen_job_ids.add(norm)
            deduped_scored.append(s)
        else:
            emit(f"   ⚠️ 去重: {s.get('title', '?')} ({norm}) 已存在，跳过")
    all_scored = deduped_scored

    # ── 第二轮：及格线附近复评 ──
    if borderline_rescore:
        low = min_score - borderline_range
        high = min_score + borderline_range
        borderline_jobs = [s for s in all_scored if low <= s.get("total_score", 0) <= high]

        if borderline_jobs:
            emit(f"\n   🔄 及格线复评：{len(borderline_jobs)} 个岗位处于 {low}-{high} 分区间，进行二次评分...")

            # 需要从原始 jobs 中找到对应的 job 数据
            url_to_job = {normalize_jobsdb_url(j.get("url", "")): j for j in jobs}

            for bi in range(0, len(borderline_jobs), batch_size):
                b_batch = borderline_jobs[bi:bi + batch_size]
                # 还原原始 job 数据用于重新评分
                original_batch = []
                for s in b_batch:
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

                # 对每个岗位用其 LLM 方向对应的权重评分
                for idx, (s, orig_job) in enumerate(zip(b_batch, original_batch)):
                    cat = s.get("llm_direction", s.get("weight_profile", "default"))
                    w = get_weights(cat, weight_profiles)

                    scored2 = _score_batch([orig_job], profile_summary, w,
                                           batch_label=f"复评 {s.get('title', '?')[:30]}")

                    if scored2:
                        s2 = scored2[0]
                        if s2.get("scores"):
                            round2_total = _calc_total_score(s2["scores"], w)
                            round1_total = s["score_rounds"][0]
                            # 取两轮平均
                            avg_scores = {}
                            for dim in ["skill", "experience", "level", "industry", "bonus"]:
                                avg_scores[dim] = round(
                                    (s.get("scores", {}).get(dim, 0) + s2["scores"].get(dim, 0)) / 2
                                )
                            avg_total = _calc_total_score(avg_scores, w)
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
    for pname, pw in weight_profiles.items():
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
