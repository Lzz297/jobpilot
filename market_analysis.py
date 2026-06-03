"""
market_analysis.py - 独立市场调研工具
指定岗位类别，主动搜索 JobsDB 并分析市场行情（技能需求、薪资、经验要求等）
"""
import os
import json
from datetime import datetime

import config
from config import (
    emit, client, OUTPUT_DIR, track_file,
    load_profile, load_yaml, parse_json_response,
    load_prompts, render_prompt,
)
from scraper import scan_jobsdb_listings, fetch_multiple_details
from pdf_renderer import render_report as render_pdf


# ============================================================
#  市场分析 prompt
# ============================================================

_ANALYSIS_SYSTEM_PROMPT = """你是一位资深人力资源市场分析师。请根据以下 <job_category> 类岗位的 JD 数据，提取并分析市场行情。

重要：technical_skills 只收录「可以学习和练习的具体技术技能」，例如编程语言、框架、数据库、云平台、协议、工具等。
以下内容不算技术技能，不要放进 technical_skills：
- 岗位职责（如 "商业开发"、"合作伙伴管理"、"项目管理"）→ 放 common_responsibilities
- 软技能（如 "沟通能力"、"团队协作"、"领导力"）→ 放 common_responsibilities
- 行业知识（如 "了解加密货币市场"）→ 放 key_trends
- 学历/证书要求 → 不放

分析要求——输出严格的 JSON 对象，不要输出其他文字：
{
  "sample_size": 实际分析的JD数量,
  "technical_skills": [
    {
      "skill": "具体技术名称（如 'Solidity Smart Contract Development'，而非笼统的 'Blockchain'）",
      "category": "编程语言/框架/数据库/云平台/DevOps/安全/协议/其他工具",
      "description": "用 1-2 句话解释这个技术是什么、在工作中具体做什么",
      "typical_tools": ["该技术领域常用的具体工具/框架/库，列 2-5 个"],
      "count": 出现次数,
      "percentage": "百分比%",
      "level": "必须/优先/加分"
    }
  ],
  "soft_skills": [
    {
      "skill": "软技能或业务能力名称",
      "description": "具体说明在该类岗位中这个能力怎么体现",
      "count": 出现次数,
      "percentage": "百分比%"
    }
  ],
  "salary_overview": {
    "ranges": [
      {"level": "Junior/Mid/Senior", "range": "薪资范围", "count": 该级别岗位数}
    ],
    "notes": "薪资相关备注（如大部分未标明薪资等）"
  },
  "experience_distribution": [
    {"range": "0-2年/3-5年/5-8年/8年+", "count": 岗位数, "percentage": "百分比%"}
  ],
  "common_responsibilities": [
    "用完整的句子描述最常见的职责，要具体（如：'设计和维护 RESTful API，支持前端和第三方系统集成'）"
  ],
  "industry_distribution": [
    {"industry": "行业名称", "count": 岗位数}
  ],
  "key_trends": [
    "趋势观察——要具体说明趋势是什么、为什么重要、对求职者意味着什么"
  ]
}

注意：
- technical_skills 按出现频次从高到低排列，最多列 20 项
- 技能名称必须具体到可以去学习的程度（如 "Ethers.js Web3 Library" 而非 "Web3"，"PostgreSQL Database" 而非 "数据库"）
- description 要让一个不了解该技能的人也能看懂它是什么
- typical_tools 列出实际使用的工具，不要笼统
- soft_skills 最多列 10 项，按频次排序
- salary_overview 只统计明确标明薪资的岗位，未标明的不要猜测
- 如果某个维度数据不足，如实说明而不要编造"""

_GAP_ANALYSIS_PROMPT = """你是一位求职策略顾问。请对比市场技能需求和候选人画像，进行差距分析。

市场技术技能需求（按频次排序）：
<technical_skills>

候选人画像：
<profile>

请输出严格的 JSON 对象，不要输出其他文字：
{
  "strengths": [
    {
      "skill": "技能完整名称",
      "description": "这个技能是什么、候选人在哪些项目中用到了它",
      "market_demand": "高/中",
      "candidate_level": "熟练/掌握/了解",
      "advantage": "候选人的这个技能比一般求职者强在哪里，有什么独特价值"
    }
  ],
  "gaps": [
    {
      "skill": "技能完整名称",
      "description": "这个技能具体是什么，在工作中用来做什么",
      "market_demand": "高/中",
      "learning_difficulty": "低/中/高",
      "current_gap": "候选人目前在这个技能上的具体差距是什么（如：有 Docker 经验但没用过 K8s 编排）",
      "learning_path": [
        "第 1 步：具体要学什么、怎么学",
        "第 2 步：做什么练习或项目来巩固",
        "第 3 步：达到面试水平需要多久"
      ],
      "priority": "高/中/低 — 附一句话说明为什么是这个优先级（如：'高 — 75% 的后端岗位要求'）"
    }
  ],
  "low_value_skills": [
    {
      "skill": "技能名称",
      "note": "市场需求低但候选人掌握——说明是否值得继续深入，或者可以如何转化为其他方向的优势"
    }
  ],
  "strategic_advice": [
    "具体的策略建议——不要说'建议学习 XX'这种空话，要说清楚：学什么、怎么学、学到什么程度、预计多久、学完后能投什么岗位"
  ]
}

注意：
- strengths: 候选人具备且市场需求高的技能，说清楚为什么是优势
- gaps: 市场需求高但候选人缺失/薄弱的技能，必须给出可执行的学习路径（不是一句笼统的建议）
- learning_path 每一步要具体到可以直接去执行（如 "在 LeetCode 刷 50 道 medium 难度的树/图题"），而不是 "加强算法能力"
- priority 要基于市场数据说明（如 "高 — 15/20 条 JD 都要求此技能"）
- strategic_advice: 综合建议，优先级排序，告诉候选人应该先补什么、后补什么、为什么"""


# ============================================================
#  主函数
# ============================================================

def analyze_market(job_category, location="Hong Kong", include_gap_analysis=True, classification="", sort_by=None):
    """
    独立市场调研：主动搜索 JobsDB 指定岗位类别，分析市场行情。

    Args:
        job_category: 岗位类别关键词，如 "Java Developer", "Web3", "AI Agent"
        location: 搜索地点，默认 "Hong Kong"
        include_gap_analysis: 是否包含个人差距分析
        classification: JobsDB 行业分类（可选）
        sort_by: 排序方式，"date" = 按发布时间, "relevance" = 按相关度
    """
    # ── 加载配置 ──
    search_cfg, _ = load_yaml("search_config.yaml")
    ma_cfg = (search_cfg or {}).get("market_analysis", {})
    cfg_max_pages = ma_cfg.get("max_pages", 3)
    cfg_max_fetch = ma_cfg.get("max_fetch_jd", 40)
    cfg_batch_size = ma_cfg.get("batch_size", 10)
    cfg_jd_max_chars = ma_cfg.get("jd_max_chars", 2000)
    cfg_sort_by = sort_by or (search_cfg or {}).get("sort_mode", "date")

    emit(f"\n{'='*50}")
    emit(f"📊 市场分析: {job_category} @ {location}")
    emit(f"{'='*50}")

    # ── Phase A: 数据采集 ──
    emit(f"\n   📡 搜索 JobsDB: {job_category}...")
    listings = scan_jobsdb_listings(job_category, location, max_pages=cfg_max_pages,
                                     classification=classification, sort_by=cfg_sort_by)

    if not listings:
        return f"❌ 未搜索到 {job_category} 相关岗位，请检查关键词或网络连接"

    emit(f"   📦 扫描到 {len(listings)} 条岗位列表")
    all_listings = list(listings)  # 保留全量列表用于保存

    # 不做预过滤，全量抓取完整 JD 后再由 LLM 分析（准确性优先）
    max_fetch = min(len(listings), cfg_max_fetch)
    urls = [item["url"] for item in listings[:max_fetch]]
    emit(f"   📄 抓取 {max_fetch} 个岗位的完整 JD...")
    details = fetch_multiple_details(urls, delay=1.5, max_jobs=max_fetch)

    # 整理有效 JD
    valid_jobs = []
    for idx, d in enumerate(details):
        if d.get("error") or not d.get("description") or len(d.get("description", "")) < 50:
            # 尝试用 snippet 兜底
            if idx < len(listings) and listings[idx].get("snippet"):
                valid_jobs.append({
                    "title": listings[idx].get("title", ""),
                    "company": listings[idx].get("company", ""),
                    "salary": listings[idx].get("salary", ""),
                    "description": listings[idx].get("snippet", ""),
                })
            continue
        valid_jobs.append({
            "title": d.get("title") or (listings[idx].get("title", "") if idx < len(listings) else ""),
            "company": d.get("company") or (listings[idx].get("company", "") if idx < len(listings) else ""),
            "salary": d.get("salary") or (listings[idx].get("salary", "") if idx < len(listings) else ""),
            "description": d.get("description", ""),
        })

    if not valid_jobs:
        return f"❌ 抓取到 JD 数据为空，无法分析"

    emit(f"   ✅ 有效 JD: {len(valid_jobs)} 条")

    # ── Phase B: LLM 市场分析 ──
    emit(f"\n   🧠 LLM 分析市场数据...")

    # 压缩 JD 数据（只保留关键信息）
    batch_results = []

    for i in range(0, len(valid_jobs), cfg_batch_size):
        batch = valid_jobs[i:i + cfg_batch_size]
        batch_num = i // cfg_batch_size + 1
        total_batches = (len(valid_jobs) + cfg_batch_size - 1) // cfg_batch_size
        emit(f"   📊 分析第 {batch_num}/{total_batches} 批（{len(batch)} 条 JD）...")

        jobs_text = ""
        for j, job in enumerate(batch, 1):
            desc = job["description"]
            if len(desc) > cfg_jd_max_chars:
                desc = desc[:cfg_jd_max_chars] + "..."
            jobs_text += f"\n--- JD {j} ---\n"
            jobs_text += f"标题: {job['title']}\n"
            if job.get("company"):
                jobs_text += f"公司: {job['company']}\n"
            if job.get("salary"):
                jobs_text += f"薪资: {job['salary']}\n"
            jobs_text += f"描述:\n{desc}\n"

        try:
            resp = client.chat.completions.create(
                model=config.MODEL_NAME,
                temperature=0,
                messages=[
                    {"role": "system", "content": render_prompt(
                        load_prompts().get("market_analysis", {}).get("analysis_system_prompt", _ANALYSIS_SYSTEM_PROMPT),
                        job_category=job_category)},
                    {"role": "user", "content": f"以下是 {len(batch)} 条 {job_category} 岗位 JD：\n{jobs_text}"}
                ]
            )
            result = parse_json_response(resp.choices[0].message.content)
            if result and isinstance(result, dict):
                batch_results.append(result)
            else:
                emit(f"   ⚠️ 第 {batch_num} 批解析失败，跳过")
        except Exception as e:
            emit(f"   ❌ 第 {batch_num} 批分析失败: {e}")

    if not batch_results:
        return "❌ LLM 分析全部失败，请稍后重试"

    # 如果只有一批，直接使用；多批则聚合
    if len(batch_results) == 1:
        analysis = batch_results[0]
    else:
        analysis = _aggregate_batch_results(batch_results, job_category)

    # ── Phase C: 差距分析 (可选) ──
    gap_analysis = None
    if include_gap_analysis:
        emit(f"\n   🔍 差距分析...")
        profile, err = load_profile()
        if err:
            emit(f"   ⚠️ 无法加载用户画像: {err}，跳过差距分析")
        else:
            gap_analysis = _run_gap_analysis(analysis, profile)

    # ── Phase D: LLM 撰写报告 ──
    emit(f"\n   📝 LLM 正在撰写分析报告...")
    report = _generate_report_via_llm(job_category, location, len(valid_jobs), analysis, gap_analysis)

    # 保存到 output/market/ 目录
    market_dir = os.path.join(OUTPUT_DIR, "market")
    os.makedirs(market_dir, exist_ok=True)
    cat_label = job_category.replace(" ", "_").replace("/", "_")[:30]
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"market/market_{cat_label}_{date_str}.md"
    report_path = os.path.join(OUTPUT_DIR, report_name)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    track_file(report_path, f"市场分析报告（{job_category}，{len(valid_jobs)} 条 JD）")

    # 生成 PDF
    emit(f"   📄 正在生成市场分析 PDF...")
    pdf_path = render_pdf(report, report_path)
    if pdf_path:
        track_file(pdf_path, f"市场分析 PDF（{job_category}）")

    # 保存 LLM 分析结论
    data_name = f"market/market_{cat_label}_{date_str}.json"
    data_path = os.path.join(OUTPUT_DIR, data_name)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({
            "job_category": job_category,
            "location": location,
            "sample_size": len(valid_jobs),
            "analysis": analysis,
            "gap_analysis": gap_analysis,
        }, f, ensure_ascii=False, indent=2)
    track_file(data_path, f"市场分析结论 JSON")

    # 保存扫描全量列表（过滤前）
    scan_name = f"market/market_{cat_label}_{date_str}_scan.json"
    scan_path = os.path.join(OUTPUT_DIR, scan_name)
    with open(scan_path, "w", encoding="utf-8") as f:
        json.dump(all_listings, f, ensure_ascii=False, indent=2)
    track_file(scan_path, f"扫描全量列表（{len(all_listings)} 条）")

    # 保存抓取的完整 JD 原文
    jd_name = f"market/market_{cat_label}_{date_str}_jds.json"
    jd_path = os.path.join(OUTPUT_DIR, jd_name)
    with open(jd_path, "w", encoding="utf-8") as f:
        json.dump(valid_jobs, f, ensure_ascii=False, indent=2)
    track_file(jd_path, f"抓取的完整 JD（{len(valid_jobs)} 条）")


    # 返回摘要
    summary = f"✅ 市场分析完成！\n\n"
    summary += f"   类别: {job_category} @ {location}\n"
    summary += f"   样本: {len(valid_jobs)} 条 JD\n"
    summary += f"   报告: {report_name}\n\n"

    # 技术技能 top 10
    skills = analysis.get("technical_skills", [])[:10]
    if skills:
        summary += "📊 技术技能 Top 10:\n"
        for sk in skills:
            desc = sk.get('description', '')
            desc_short = f" — {desc[:60]}..." if desc and len(desc) > 60 else (f" — {desc}" if desc else "")
            summary += f"   {sk.get('skill', '?')}: {sk.get('count', '?')} 次（{sk.get('percentage', '?')}）{desc_short}\n"
        summary += "\n"

    # 薪资概况
    salary = analysis.get("salary_overview", {})
    ranges = salary.get("ranges", [])
    if ranges:
        summary += "💰 薪资概况:\n"
        for r in ranges:
            summary += f"   {r.get('level', '?')}: {r.get('range', '?')}（{r.get('count', '?')} 个岗位）\n"
        summary += "\n"

    # 差距分析摘要
    if gap_analysis:
        gaps = gap_analysis.get("gaps", [])[:5]
        if gaps:
            summary += "⚠️ 技能差距 Top 5:\n"
            for g in gaps:
                priority = g.get('priority', '')
                gap_desc = g.get('current_gap', '') or g.get('recommendation', '')
                summary += f"   {g.get('skill', '?')}（{g.get('learning_difficulty', '?')}难度 | {priority}）\n"
                if gap_desc:
                    summary += f"      → {gap_desc[:80]}\n"
            summary += "\n"

        advice = gap_analysis.get("strategic_advice", [])[:3]
        if advice:
            summary += "💡 策略建议:\n"
            for a in advice:
                summary += f"   - {a}\n"

    return summary


# ============================================================
#  批量市场分析
# ============================================================

def batch_analyze_market(tasks, location="Hong Kong", include_gap_analysis=True, sort_by=None):
    """
    批量市场分析：依次分析多个岗位类别。

    Args:
        tasks: 岗位列表，每项包含 category 和可选的 classification
               例如: [{"category": "AI Agent", "classification": "information-communication-technology"}, {"category": "Web3"}]
        location: 搜索地点，默认 "Hong Kong"
        include_gap_analysis: 是否包含个人差距分析
        sort_by: 排序方式，"date" = 按发布时间, "relevance" = 按相关度
    """
    if not tasks or not isinstance(tasks, list):
        return "❌ 请提供至少一个岗位类别"

    total = len(tasks)
    results = []

    for i, task in enumerate(tasks, 1):
        category = task.get("category", "").strip()
        classification = task.get("classification", "").strip()
        if not category:
            continue

        emit(f"\n{'='*50}")
        emit(f"📋 批量任务进度: {i}/{total}")
        emit(f"{'='*50}")

        result = analyze_market(
            job_category=category,
            location=location,
            include_gap_analysis=include_gap_analysis,
            classification=classification,
            sort_by=sort_by,
        )
        results.append(f"--- [{i}/{total}] {category} ---\n{result}")

    if not results:
        return "❌ 没有有效的岗位类别"

    summary = f"🎉 批量市场分析全部完成！共 {len(results)}/{total} 个岗位\n\n"
    summary += "\n\n".join(results)
    return summary


# ============================================================
#  辅助函数
# ============================================================

def _aggregate_batch_results(batch_results, job_category):
    """将多批分析结果聚合为一个综合结果。"""
    total_sample = sum(br.get("sample_size", 0) for br in batch_results)

    # 合并技术技能
    skill_counts = {}
    for br in batch_results:
        for sk in br.get("technical_skills", []):
            name = sk.get("skill", "")
            if name:
                if name not in skill_counts:
                    skill_counts[name] = {
                        "count": 0, "level": sk.get("level", "加分"),
                        "category": sk.get("category", ""),
                        "description": sk.get("description", ""),
                        "typical_tools": sk.get("typical_tools", []),
                    }
                skill_counts[name]["count"] += sk.get("count", 1)

    technical_skills = []
    for name, info in sorted(skill_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:20]:
        pct = f"{info['count'] / max(total_sample, 1) * 100:.0f}%"
        technical_skills.append({
            "skill": name, "count": info["count"],
            "percentage": pct, "level": info["level"],
            "category": info["category"],
            "description": info["description"],
            "typical_tools": info["typical_tools"],
        })

    # 合并软技能
    soft_counts = {}
    for br in batch_results:
        for sk in br.get("soft_skills", []):
            name = sk.get("skill", "")
            if name:
                if name not in soft_counts:
                    soft_counts[name] = {"count": 0, "description": sk.get("description", "")}
                soft_counts[name]["count"] += sk.get("count", 1)
    soft_skills = []
    for name, info in sorted(soft_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
        pct = f"{info['count'] / max(total_sample, 1) * 100:.0f}%"
        soft_skills.append({"skill": name, "count": info["count"], "percentage": pct, "description": info["description"]})

    # 合并薪资
    all_ranges = []
    salary_notes = []
    for br in batch_results:
        so = br.get("salary_overview", {})
        all_ranges.extend(so.get("ranges", []))
        if so.get("notes"):
            salary_notes.append(so["notes"])

    # 合并经验分布
    exp_counts = {}
    for br in batch_results:
        for ed in br.get("experience_distribution", []):
            r = ed.get("range", "")
            if r:
                exp_counts[r] = exp_counts.get(r, 0) + ed.get("count", 0)
    exp_dist = []
    for r, c in sorted(exp_counts.items()):
        exp_dist.append({"range": r, "count": c, "percentage": f"{c / max(total_sample, 1) * 100:.0f}%"})

    # 合并职责
    all_resp = []
    for br in batch_results:
        all_resp.extend(br.get("common_responsibilities", []))
    # 去重取前 10
    seen = set()
    unique_resp = []
    for r in all_resp:
        if r not in seen:
            seen.add(r)
            unique_resp.append(r)
    unique_resp = unique_resp[:10]

    # 合并行业
    ind_counts = {}
    for br in batch_results:
        for ind in br.get("industry_distribution", []):
            name = ind.get("industry", "")
            if name:
                ind_counts[name] = ind_counts.get(name, 0) + ind.get("count", 0)
    ind_dist = [{"industry": k, "count": v} for k, v in sorted(ind_counts.items(), key=lambda x: x[1], reverse=True)]

    # 合并趋势
    all_trends = []
    for br in batch_results:
        all_trends.extend(br.get("key_trends", []))
    seen = set()
    unique_trends = []
    for t in all_trends:
        if t not in seen:
            seen.add(t)
            unique_trends.append(t)

    # 合并语言要求
    lang_req = {"english": {}, "chinese": {}, "summary": ""}
    for br in batch_results:
        lr = br.get("language_requirements", {})
        for lang_key in ("english", "chinese"):
            for sub_key, sub_val in lr.get(lang_key, {}).items():
                if sub_key not in lang_req[lang_key]:
                    lang_req[lang_key][sub_key] = {"count": 0, "percentage": "0%"}
                if isinstance(sub_val, dict):
                    lang_req[lang_key][sub_key]["count"] += sub_val.get("count", 0)
        if lr.get("summary"):
            lang_req["summary"] = lr["summary"]
    # 重算百分比
    for lang_key in ("english", "chinese"):
        for sub_key in lang_req[lang_key]:
            c = lang_req[lang_key][sub_key]["count"]
            lang_req[lang_key][sub_key]["percentage"] = f"{c / max(total_sample, 1) * 100:.0f}%"

    # 合并学历要求
    edu_req = {}
    edu_note = ""
    for br in batch_results:
        er = br.get("education_requirements", {})
        for key, val in er.items():
            if key == "note":
                edu_note = val
                continue
            if isinstance(val, dict):
                if key not in edu_req:
                    edu_req[key] = {"count": 0, "percentage": "0%"}
                edu_req[key]["count"] += val.get("count", 0)
    for key in edu_req:
        c = edu_req[key]["count"]
        edu_req[key]["percentage"] = f"{c / max(total_sample, 1) * 100:.0f}%"
    if edu_note:
        edu_req["note"] = edu_note

    # 合并公司画像
    size_counts = {}
    all_notable = []
    company_note = ""
    for br in batch_results:
        cp = br.get("company_profile", {})
        for sd in cp.get("size_distribution", []):
            sz = sd.get("size", "")
            if sz:
                size_counts[sz] = size_counts.get(sz, 0) + sd.get("count", 0)
        all_notable.extend(cp.get("notable_companies", []))
        if cp.get("note"):
            company_note = cp["note"]
    company_profile = {
        "size_distribution": [{"size": k, "count": v} for k, v in size_counts.items()],
        "notable_companies": list(dict.fromkeys(all_notable))[:10],
        "note": company_note,
    }

    # 合并面试线索
    interview = {}
    interview_note = ""
    for br in batch_results:
        ih = br.get("interview_hints", {})
        for key, val in ih.items():
            if key == "note":
                interview_note = val
                continue
            if isinstance(val, dict):
                if key not in interview:
                    interview[key] = {"count": 0, "percentage": "0%"}
                interview[key]["count"] += val.get("count", 0)
    for key in interview:
        c = interview[key]["count"]
        interview[key]["percentage"] = f"{c / max(total_sample, 1) * 100:.0f}%"
    if interview_note:
        interview["note"] = interview_note

    return {
        "sample_size": total_sample,
        "technical_skills": technical_skills,
        "soft_skills": soft_skills,
        "salary_overview": {"ranges": all_ranges, "notes": "; ".join(salary_notes)},
        "experience_distribution": exp_dist,
        "common_responsibilities": unique_resp,
        "industry_distribution": ind_dist,
        "key_trends": unique_trends[:8],
        "language_requirements": lang_req,
        "education_requirements": edu_req,
        "company_profile": company_profile,
        "interview_hints": interview,
    }


def _run_gap_analysis(analysis, profile):
    """用 LLM 做候选人 vs 市场需求的差距分析。"""
    skills_text = json.dumps(analysis.get("technical_skills", []), ensure_ascii=False, indent=2)

    profile_summary = json.dumps({
        "skills": profile.get("skills", {}),
        "work_experience": [
            {"title": exp.get("title"), "tech_stack": exp.get("tech_stack", [])}
            for exp in profile.get("work_experience", [])
        ],
        "certifications": profile.get("certifications", []),
    }, ensure_ascii=False, indent=2)

    try:
        resp = client.chat.completions.create(
            model=config.MODEL_NAME,
            temperature=0,
            messages=[
                {"role": "system", "content": render_prompt(
                    load_prompts().get("market_analysis", {}).get("gap_analysis_prompt", _GAP_ANALYSIS_PROMPT),
                    technical_skills=skills_text, profile=profile_summary)},
                {"role": "user", "content": "请进行差距分析。"}
            ]
        )
        result = parse_json_response(resp.choices[0].message.content)
        if result and isinstance(result, dict):
            return result
        else:
            emit("   ⚠️ 差距分析解析失败")
            return None
    except Exception as e:
        emit(f"   ❌ 差距分析失败: {e}")
        return None


def _generate_report_via_llm(job_category, location, sample_size, analysis, gap_analysis):
    """Stage 2: 用 LLM 将结构化 JSON 数据撰写成专业的 Markdown 分析报告。"""
    # 默认 prompt（prompts.yaml 中未配置时的回退）
    default_prompt = (
        "你是一位资深市场分析报告撰写专家。请根据以下结构化数据，撰写一份完整的 <job_category> 岗位市场分析报告。\n\n"
        "岗位类别: <job_category> | 地点: <location> | 样本量: <sample_size> 条 JD\n\n"
        "市场分析数据：\n<analysis_json>\n\n差距分析数据：\n<gap_analysis_json>\n\n"
        "规则：JSON 中每个有数据的维度都必须体现，禁止省略或编造。输出纯 Markdown 格式。"
    )

    prompt_template = load_prompts().get("market_analysis", {}).get("report_prompt", default_prompt)

    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)
    gap_json = json.dumps(gap_analysis, ensure_ascii=False, indent=2) if gap_analysis else "无"

    prompt = render_prompt(
        prompt_template,
        job_category=job_category,
        location=location,
        sample_size=str(sample_size),
        analysis_json=analysis_json,
        gap_analysis_json=gap_json,
    )

    try:
        resp = client.chat.completions.create(
            model=config.MODEL_NAME,
            temperature=0,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请撰写完整的市场分析报告。"},
            ]
        )
        report = resp.choices[0].message.content.strip()
        # 去除 LLM 可能添加的 markdown 代码块包裹
        if report.startswith("```markdown"):
            report = report[len("```markdown"):].strip()
        if report.startswith("```"):
            report = report[3:].strip()
        if report.endswith("```"):
            report = report[:-3].strip()
        return report
    except Exception as e:
        emit(f"   ❌ LLM 撰写报告失败: {e}，回退到基础格式")
        # 回退：输出最基础的 JSON dump，确保数据不丢
        fallback = f"# {job_category} 市场分析报告\n\n"
        fallback += f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        fallback += f"- 搜索地点: {location}\n"
        fallback += f"- 样本量: {sample_size} 条 JD\n\n"
        fallback += "## 市场分析数据\n\n```json\n" + analysis_json + "\n```\n\n"
        if gap_analysis:
            fallback += "## 差距分析数据\n\n```json\n" + gap_json + "\n```\n"
        return fallback
