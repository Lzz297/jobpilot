"""
job_search.py - 三层漏斗搜索（扫描 → 基础清洗 → 抓取 JD）
"""
import os
import json
from datetime import datetime

import config
from config import (
    emit, OUTPUT_DIR, track_file,
    load_search_config_dict,
    start_new_run,
)
from scraper import (
    scan_jobsdb_listings,
    fetch_multiple_details,
    normalize_jobsdb_url,
)


# ============================================================
#  第二层-A：基础清洗（代码级，毫秒完成）
# ============================================================

def basic_filter(listings, config):
    """
    极低成本的硬过滤，只做两件事：
    1. 去掉标题为空的
    2. 去掉用户明确排除的公司
    """
    exclude_companies = [
        c.lower().strip()
        for c in config.get("filters", {}).get("exclude_companies", [])
    ]

    passed = []
    rejected = []

    for job in listings:
        title = job.get("title", "").strip()
        company_lower = job.get("company", "").lower().strip()

        if not title:
            job["reject_reasons"] = ["标题为空"]
            rejected.append(job)
        elif exclude_companies and company_lower in exclude_companies:
            job["reject_reasons"] = [f"排除公司: {job.get('company', '')}"]
            rejected.append(job)
        else:
            passed.append(job)

    return passed, rejected


# ============================================================
#  岗位搜索（三层漏斗：扫描 → 基础清洗 → 抓取JD）
# ============================================================

def search_jobs():
    """
    三层漏斗搜索：
      第一层 - 扫描 JobsDB 搜索列表页（只拿标题/公司/摘要，不打开详情页）
      第二层 - 基础清洗（排除空标题 + 排除公司）
      第三层 - 全量抓取完整 JD
    """
    # ── 读取配置 ──
    config, err = load_search_config_dict()
    if err:
        return err

    search_queries = config.get("search_queries", [])
    max_total = config.get("max_total_results", 30)
    max_pages_per_query = config.get("max_pages_per_query", 6)

    # =============================================================
    #  第一层：广撒网 — 扫描 JobsDB 搜索列表
    # =============================================================
    emit(f"\n{'='*50}")
    emit(f"📡 第一层：扫描 JobsDB 搜索列表")
    emit(f"{'='*50}")

    all_listings = []
    seen_ids = set()

    for sq in search_queries:
        keywords = sq.get("keywords", "")
        location = sq.get("location", "Hong Kong")
        classification = sq.get("classification", "")

        items = scan_jobsdb_listings(keywords, location, max_pages=max_pages_per_query,
                                     classification=classification)

        new_count = 0
        for item in items:
            jid = item.get("job_id", "")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_listings.append(item)
                new_count += 1

        emit(f"   [{keywords}] 新增 {new_count} 条（去重后），累计 {len(all_listings)}")

    emit(f"\n   📦 第一层完成: 共扫描到 {len(all_listings)} 条岗位（已跨搜索词去重）")

    if not all_listings:
        return "❌ 未找到任何岗位，请检查搜索关键词或网络连接"

    # =============================================================
    #  第二层：基础清洗（仅排除空标题和排除公司）
    # =============================================================
    emit(f"\n{'='*50}")
    emit(f"🧹 第二层：基础清洗")
    emit(f"{'='*50}")

    cleaned, basic_rejected = basic_filter(all_listings, config)
    if basic_rejected:
        emit(f"   🧹 排除 {len(basic_rejected)} 条（空标题/排除公司）")

    # 诊断：标题全为空
    if not cleaned:
        empty_count = sum(1 for j in all_listings if not j.get("title", "").strip())
        if empty_count > len(all_listings) * 0.8:
            return (
                "❌ 扫描到 {0} 条岗位，但标题全部为空！\n\n"
                "这意味着 JobsDB 的页面结构已更新，scraper 的选择器需要修复。\n"
                "请检查控制台的 DEBUG 输出，将 keys 信息反馈给开发者。\n\n"
                "💡 临时解决办法：\n"
                "  1. 用「查看这个岗位 URL」直接抓取单个岗位（详情页解析通常不受影响）\n"
                "  2. 手动在 JobsDB 网站搜索，复制岗位 URL 给我"
            ).format(len(all_listings))

    all_rejected = basic_rejected
    emit(f"   ✅ 清洗后: {len(cleaned)} 条")

    # =============================================================
    #  第三层：全量抓取完整 JD（准确性优先，不做 LLM 预过滤）
    # =============================================================
    to_fetch = cleaned[:max_total]

    emit(f"\n{'='*50}")
    emit(f"📄 第三层：抓取完整 JD（{len(to_fetch)} 个岗位）")
    emit(f"{'='*50}")

    all_jobs = []
    seen_job_ids = set()

    if to_fetch:
        urls = [item["url"] for item in to_fetch]
        details = fetch_multiple_details(urls, delay=1.5, max_jobs=len(to_fetch))

        for idx, d in enumerate(details):
            listing_info = to_fetch[idx] if idx < len(to_fetch) else {}

            if d.get("error") or not d.get("description") or len(d.get("description", "")) < 50:
                if listing_info.get("snippet") and len(listing_info["snippet"]) > 20:
                    norm = normalize_jobsdb_url(listing_info.get("url", ""))
                    if norm not in seen_job_ids:
                        seen_job_ids.add(norm)
                        all_jobs.append({
                            "title": listing_info.get("title", "未知岗位"),
                            "company": listing_info.get("company", ""),
                            "location": listing_info.get("location", ""),
                            "salary": listing_info.get("salary", ""),
                            "description": listing_info.get("snippet", ""),
                            "url": norm,
                            "jd_length": len(listing_info.get("snippet", "")),
                            "source": "snippet",
                        })
                continue

            norm = normalize_jobsdb_url(d.get("url", ""))
            if norm in seen_job_ids:
                continue
            seen_job_ids.add(norm)

            all_jobs.append({
                "title": d.get("title") or listing_info.get("title", "未知岗位"),
                "company": d.get("company") or listing_info.get("company", ""),
                "location": d.get("location") or listing_info.get("location", ""),
                "salary": d.get("salary") or listing_info.get("salary", ""),
                "description": d.get("description", ""),
                "url": norm,
                "jd_length": len(d.get("description", "")),
                "posted_date": listing_info.get("posted_date", ""),
                "classification": listing_info.get("classification", ""),
                "source": "full_jd",
            })

    # ── 编号 ──
    for i, job in enumerate(all_jobs):
        job["index"] = i + 1

    # ── 保存到 run 目录 ──
    run_dir = start_new_run()
    filepath = os.path.join(run_dir, "raw_jobs.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)
    track_file(filepath, f"岗位搜索原始数据（{len(all_jobs)} 个岗位的 JD）")

    # ── 保存第一层全量扫描列表 ──
    scan_path = os.path.join(run_dir, "scan_listings.json")
    with open(scan_path, "w", encoding="utf-8") as f:
        json.dump(all_listings, f, ensure_ascii=False, indent=2)
    track_file(scan_path, f"第一层扫描全量列表（{len(all_listings)} 条）")

    # ── 保存被过滤的岗位 ──
    rejected_path = os.path.join(run_dir, "rejected_jobs.json")
    rejected_data = []
    for r in all_rejected:
        rejected_data.append({
            "title": r.get("title", ""),
            "company": r.get("company", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", "")[:200],
            "reject_reasons": r.get("reject_reasons", []),
            "reject_stage": "basic",
        })
    with open(rejected_path, "w", encoding="utf-8") as f:
        json.dump(rejected_data, f, ensure_ascii=False, indent=2)
    track_file(rejected_path, f"被过滤岗位详情（{len(all_rejected)} 条）")

    # ── 保存过滤统计 ──
    stats = {
        "scan_total": len(all_listings),
        "basic_rejected": len(basic_rejected),
        "filter_passed": len(cleaned),
        "jd_fetched": len(all_jobs),
        "full_jd_count": sum(1 for j in all_jobs if j.get("source") == "full_jd"),
        "snippet_count": sum(1 for j in all_jobs if j.get("source") == "snippet"),
        "rejected_samples": [
            {"title": r.get("title", ""), "reasons": r.get("reject_reasons", [])}
            for r in all_rejected
        ],
    }
    stats_path = os.path.join(run_dir, "filter_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    track_file(stats_path, f"过滤统计数据")

    # ── 返回摘要 ──
    full_jd_count = stats["full_jd_count"]
    snippet_count = stats["snippet_count"]

    summary = f"✅ 搜索完成！\n\n"
    summary += f"   📡 第一层 扫描: {len(all_listings)} 条（{len(search_queries)} 组搜索词）\n"
    summary += f"   🧹 第二层 清洗: {len(cleaned)} 条通过 / {len(basic_rejected)} 条排除（空标题/排除公司）\n"
    summary += f"   📄 第三层 抓取: {len(all_jobs)} 条（完整JD {full_jd_count} | snippet {snippet_count}）\n"
    summary += f"   💾 保存到: {os.path.basename(run_dir)}/\n\n"

    summary += "--- 岗位列表 ---\n"
    for job in all_jobs[:15]:
        company_str = f" @ {job['company']}" if job.get("company") else ""
        salary_str = f" | 💰 {job['salary']}" if job.get("salary") else ""
        jd_flag = "📄" if job.get("source") == "full_jd" else "📋"
        summary += f"{job['index']}. {jd_flag} {job['title']}{company_str}{salary_str}\n"
        summary += f"   {job['description'][:120]}\n"
        summary += f"   {job['url']}\n\n"
    if len(all_jobs) > 15:
        summary += f"...还有 {len(all_jobs) - 15} 条，完整数据在文件中\n"

    return summary
