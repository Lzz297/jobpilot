"""
resume_gen.py - 多模式简历生成（三语 PDF）

支持 3 种输入模式：
  1. by_direction — 基于匹配数据按方向批量生成（需先 search + match）
  2. job_index    — 基于匹配排名中的岗位（需先 search + match）
  3. jd_text      — 基于用户粘贴的任意 JD 文本
"""
import os
import json
import yaml
from datetime import datetime

from config import (
    emit, llm_call, OUTPUT_DIR, track_file,
    load_profile, load_yaml, load_search_config_dict, parse_json_response,
    get_current_run_dir, get_latest_run_dir,
    load_prompts, render_prompt,
)
from pdf_renderer import render_resume as render_pdf
from job_match import classify_job, get_weights

# 模块级变量：最近一次简历核查报告 + 简历 Markdown。供 web_app.py 等调用方获取。
last_check_report: list[dict] = []
last_resume_md: str = ""

# ============================================================
#  各模式的 LLM 系统 prompt
# ============================================================

def _load_resume_prompt(key: str) -> str:
    """加载简历 prompt。唯一来源为 prompts.yaml，缺失时报错。"""
    template = load_prompts().get("resume", {}).get(key)
    if not template:
        raise RuntimeError(f"resume.{key} 在 prompts.yaml 中缺失或为空")
    return template

# ============================================================
#  Cover Letter prompt (已废弃 — 以下常量仅为历史保留，不再被引用)

# ============================================================
#  方向聚合分析 prompt

# ============================================================
#  方向聚合分析 + 批量生成
# ============================================================

def _aggregate_direction_requirements(matched_jobs, profile_text, search_cfg):
    """按方向聚合达标岗位的 JD，调用 LLM 提取共性需求并做三级技能分类"""
    weight_rules = search_cfg.get("matching", {}).get("weight_rules", {})

    groups = {}
    for job in matched_jobs:
        direction = job.get("llm_direction") or job.get("weight_profile", "")
        if not direction:
            direction = classify_job(job.get("title", ""), weight_rules)
        if direction == "default":
            continue
        groups.setdefault(direction, []).append(job)

    if not groups:
        return {}

    template = _load_resume_prompt("aggregate_system_prompt")

    results = {}
    for direction, jobs in groups.items():
        if len(jobs) < 2:
            emit(f"   ⚠️ {direction} 方向只有 {len(jobs)} 个岗位，跳过聚合")
            continue

        emit(f"   🔍 聚合分析 {direction} 方向（{len(jobs)} 个岗位）...")

        jds_text = ""
        for j, job in enumerate(jobs[:15], 1):
            jds_text += f"\n--- 岗位 {j}: {job.get('title', '')} @ {job.get('company', '')} ---\n"
            desc = job.get("description", "")
            if len(desc) > 2000:
                desc = desc[:2000] + "\n...(截断)"
            jds_text += desc + "\n"

        system_prompt = render_prompt(template, profile_summary=profile_text)

        try:
            # 主路径：Instructor + Pydantic 结构化输出
            from engine.contracts import DirectionAggregationResult
            result = llm_call(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": f"方向：{direction}\n\n以下是该方向 {len(jobs)} 个达标岗位的 JD：\n{jds_text}"}],
                temperature=0, thinking={"type": "disabled"},
                response_model=DirectionAggregationResult,
            )
            parsed = result.model_dump()
            parsed["direction"] = direction
            parsed["job_count"] = len(jobs)
            results[direction] = parsed
            dm = len(parsed.get("common_requirements", {}).get("direct_match", []))
            ql = len(parsed.get("common_requirements", {}).get("quick_learnable", []))
            emit(f"     ✅ {direction}: 直接匹配 {dm} 项，可补齐 {ql} 项")
        except Exception:
            # 回退：旧方式（parse_json_response）
            try:
                msg = llm_call(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": f"方向：{direction}\n\n以下是该方向 {len(jobs)} 个达标岗位的 JD：\n{jds_text}"}],
                    temperature=0, thinking={"type": "disabled"},
                )
                parsed = parse_json_response(msg.content)
                if parsed and isinstance(parsed, dict):
                    parsed["direction"] = direction
                    parsed["job_count"] = len(jobs)
                    results[direction] = parsed
                    dm = len(parsed.get("common_requirements", {}).get("direct_match", []))
                    ql = len(parsed.get("common_requirements", {}).get("quick_learnable", []))
                    emit(f"     ✅ {direction}: 直接匹配 {dm} 项，可补齐 {ql} 项")
                else:
                    emit(f"     ⚠️ {direction} 聚合分析返回格式异常，跳过")
            except Exception as e:
                emit(f"     ❌ {direction} 聚合分析失败: {e}")

    return results

def _generate_for_direction_batch(profile, profile_text, template_text, base_rules, resume_prompts, output_langs=None):
    """基于匹配数据按方向批量生成简历"""
    run_dir = get_current_run_dir() or get_latest_run_dir()
    if not run_dir:
        return "错误：还没有匹配分析结果，请先执行搜索和匹配"
    matched_path = os.path.join(run_dir, "matched_jobs.json")
    if not os.path.exists(matched_path):
        return "错误：还没有匹配分析结果，请先执行匹配分析"

    with open(matched_path, "r", encoding="utf-8") as f:
        matched_jobs = json.load(f)

    if not matched_jobs:
        return "匹配结果为空，无法按方向生成简历"

    from config import get_campaign_config
    campaign_config = get_campaign_config()
    search_cfg = campaign_config if campaign_config else {}

    emit(f"\n{'='*50}")
    emit(f"📊 第一步：按方向聚合分析（{len(matched_jobs)} 个达标岗位）")
    emit(f"{'='*50}")

    agg_results = _aggregate_direction_requirements(matched_jobs, profile_text, search_cfg)

    if not agg_results:
        return "没有足够的岗位数据进行方向聚合（每个方向至少需要 2 个达标岗位）"

    agg_path = os.path.join(run_dir, "direction_analysis.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(agg_results, f, ensure_ascii=False, indent=2)
    track_file(agg_path, f"方向聚合分析（{len(agg_results)} 个方向）")

    emit(f"\n{'='*50}")
    emit(f"📝 第二步：按方向生成简历（{len(agg_results)} 个方向）")
    emit(f"{'='*50}")

    all_results = []

    for direction, agg_data in agg_results.items():
        emit(f"\n   🎯 生成 {direction} 方向简历...")
        agg_text = json.dumps(agg_data, ensure_ascii=False, indent=2)

        system_content = render_prompt(
            _load_resume_prompt("prompt_for_direction_data"),
            direction=direction, template=template_text, base_rules=base_rules)

        user_content = (
            f"候选人完整档案：\n{profile_text}\n\n"
            f"「{direction}」方向市场需求聚合数据：\n{agg_text}\n\n"
            f"请根据以上信息生成一份面向 {direction} 方向的简历。"
        )

        cl_prompt = render_prompt(
            _load_resume_prompt("cl_for_direction_data"),
            direction=direction)

        result = _call_llm_and_save(
            system_content, user_content, direction,
            mode_label="方向聚合", job_label=f"{direction} 方向（基于 {agg_data.get('job_count', '?')} 个岗位）",
            cl_prompt=cl_prompt, output_langs=output_langs)
        all_results.append((direction, result))

    output = f"✅ 按方向批量简历生成完成！（共 {len(all_results)} 个方向）\n\n"
    for direction, result in all_results:
        output += f"{'─'*40}\n"
        output += f"📁 {direction} 方向\n"
        output += f"{'─'*40}\n"
        output += result + "\n\n"

    return output

# ============================================================
#  主函数：统一入口
# ============================================================

def generate_resume(job_index=None, jd_text=None, by_direction=False, output_langs=None, profile=None):
    """
    多模式简历生成。根据传入参数自动选择模式：
      - by_direction: 基于匹配数据按方向批量生成（需先 search + match）
      - job_index: 基于匹配排名中的岗位
      - jd_text: 基于用户粘贴的 JD 文本

    output_langs: 可选，指定输出语言子集，如 ["en", "hk"]。不传则输出全部三种。
    profile: 用户画像字典（不传则从 instances/users/ 自动加载）
    """
    # ── 加载公共资源 ──
    if profile is None:
        profile = load_profile()

    template_config, _ = load_yaml("resume_template.yaml")
    template_config = template_config or {}

    guide_config, _ = load_yaml("resume_guide.yaml")
    guide_text = yaml.dump(guide_config, allow_unicode=True, default_flow_style=False) if guide_config else ""

    profile_text = yaml.dump(profile, allow_unicode=True, default_flow_style=False)
    template_text = yaml.dump(template_config, allow_unicode=True, default_flow_style=False)

    # ── 加载 YAML prompt（优先 prompts.yaml，缺失时回退硬编码默认值） ──
    resume_prompts = load_prompts().get("resume", {})

    # 将指南注入 base_rules
    base_rules_template = _load_resume_prompt("base_rules")
    base_rules = render_prompt(base_rules_template, guide=guide_text)

    if by_direction:
        return _generate_for_direction_batch(
            profile, profile_text, template_text, base_rules, resume_prompts, output_langs=output_langs)
    elif job_index is not None:
        return _generate_for_matched_job(
            job_index, profile, profile_text, template_text, base_rules, resume_prompts, output_langs=output_langs)
    elif jd_text:
        return _generate_for_jd_text(
            jd_text, profile_text, template_text, base_rules, resume_prompts, output_langs=output_langs)
    else:
        return "请指定简历生成模式：by_direction=true / job_index=N / jd_text=\"...\""

# ============================================================
#  模式 1：基于匹配岗位
# ============================================================

def _generate_for_matched_job(job_index, profile, profile_text, template_text, base_rules, resume_prompts, output_langs=None):
    """从匹配结果中选择岗位生成定制简历"""
    run_dir = get_current_run_dir() or get_latest_run_dir()
    if not run_dir:
        return "错误：还没有匹配分析结果，请先执行匹配分析"
    matched_path = os.path.join(run_dir, "matched_jobs.json")
    if not os.path.exists(matched_path):
        return "错误：还没有匹配分析结果，请先执行匹配分析"

    with open(matched_path, "r", encoding="utf-8") as f:
        matched_jobs = json.load(f)

    if job_index < 1 or job_index > len(matched_jobs):
        return f"错误：岗位编号 {job_index} 无效，有效范围 1-{len(matched_jobs)}"

    target_job = matched_jobs[job_index - 1]
    job_text = json.dumps(target_job, ensure_ascii=False, indent=2)
    job_label = target_job.get("title", "未知岗位")

    emit(f"   📝 模式: 匹配岗位 | 正在为「{job_label}」生成定制简历...")

    system_content = render_prompt(
        _load_resume_prompt("prompt_for_job"),
        template=template_text, base_rules=base_rules)
    user_content = f"候选人完整档案：\n{profile_text}\n\n目标岗位（含匹配分析）：\n{job_text}\n\n请生成定制简历。"
    file_label = job_label
    company = target_job.get("company", "")

    return _call_llm_and_save(
        system_content, user_content, file_label,
        mode_label="匹配岗位", job_label=job_label, company=company,
        cl_prompt=_load_resume_prompt("cover_letter_prompt"), output_langs=output_langs)

# ============================================================
#  模式 2：基于 JD 文本
# ============================================================

def _generate_for_jd_text(jd_text, profile_text, template_text, base_rules, resume_prompts, output_langs=None):
    """基于用户粘贴的 JD 文本生成定制简历"""
    # 尝试从 JD 中提取岗位名称
    first_line = jd_text.strip().split("\n")[0][:80]
    job_label = first_line if len(first_line) > 3 else "自定义JD"

    emit(f"   📝 模式: JD 文本 | 正在根据粘贴的 JD 生成定制简历...")

    system_content = render_prompt(
        _load_resume_prompt("prompt_for_jd_text"),
        template=template_text, base_rules=base_rules)
    user_content = f"候选人完整档案：\n{profile_text}\n\n目标岗位 JD：\n{jd_text}\n\n请生成定制简历。"

    return _call_llm_and_save(
        system_content, user_content, job_label,
        mode_label="JD 文本", job_label=job_label,
        cl_prompt=_load_resume_prompt("cover_letter_prompt"), output_langs=output_langs)

# ============================================================
#  模式 3：基于岗位方向
# ============================================================

# ============================================================
#  公共：调用 LLM + 保存文件
# ============================================================

def _strip_code_block(text):
    """去除 LLM 返回的 markdown code block 包裹"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    return text

def _make_safe_label(label):
    """生成安全的文件名片段"""
    return "".join(
        c if c.isalnum() or c in " _-" else "_" for c in label
    )[:30].strip()

_LANG_LABELS = {"en": "英文", "hk": "繁體中文", "cn": "简体中文"}

def _review_resume(resume_md, file_label, resumes_dir, date_str):
    """对英文简历调用 resume_review_prompt 做质量审查。"""
    review_prompt = _load_resume_prompt("resume_review_prompt")

    emit("   🔍 正在审查英文简历质量...")

    try:
        # 主路径：Instructor + Pydantic 结构化输出
        from engine.contracts import ResumeReviewResult
        result = llm_call(
            [{"role": "system", "content": review_prompt},
             {"role": "user", "content": resume_md}],
            temperature=0, thinking={"type": "disabled"},
            response_model=ResumeReviewResult,
        )
        review = result.model_dump()

        safe_label = _make_safe_label(file_label)
        review_path = os.path.join(
            resumes_dir, f"resume_review_{safe_label}_{date_str}.json")
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(review, f, ensure_ascii=False, indent=2)
        track_file(review_path, "简历审查报告 JSON")

        score = review.get("overall_score", "?")
        top3 = review.get("top_3_improvements", [])
        summary = f"\n📋 简历审查结果: 总评 {score}\n"
        if top3:
            summary += "   Top 3 改进建议:\n"
            for i, tip in enumerate(top3, 1):
                summary += f"   {i}. {tip}\n"

        return review, summary

    except Exception:
        # 回退：旧方式（parse_json_response）
        try:
            msg = llm_call(
                [{"role": "system", "content": review_prompt},
                 {"role": "user", "content": resume_md}],
                temperature=0, thinking={"type": "disabled"},
            )
            review = parse_json_response(msg.content)

            if not review or not isinstance(review, dict):
                emit("   ⚠️ 简历审查返回格式异常，跳过")
                return None, ""

            safe_label = _make_safe_label(file_label)
            review_path = os.path.join(
                resumes_dir, f"resume_review_{safe_label}_{date_str}.json")
            with open(review_path, "w", encoding="utf-8") as f:
                json.dump(review, f, ensure_ascii=False, indent=2)
            track_file(review_path, "简历审查报告 JSON")

            score = review.get("overall_score", "?")
            top3 = review.get("top_3_improvements", [])
            summary = f"\n📋 简历审查结果: 总评 {score}\n"
            if top3:
                summary += "   Top 3 改进建议:\n"
                for i, tip in enumerate(top3, 1):
                    summary += f"   {i}. {tip}\n"

            return review, summary

        except Exception as e:
            emit(f"   ⚠️ 简历审查失败: {e}")
            return None, ""

_TRANSLATE_LANG_NAMES = {"hk": "繁體中文（香港用語）", "cn": "简体中文"}

def _call_llm_and_save(system_content, user_content, file_label,
                       mode_label="", job_label="", company="",
                       cl_prompt=None, output_langs=None):
    """英文先行 → 审查 → 定稿 → 翻译到其他语言"""
    run_dir = get_current_run_dir() or get_latest_run_dir()
    if run_dir:
        resumes_dir = os.path.join(run_dir, "resumes")
    else:
        resumes_dir = os.path.join(OUTPUT_DIR, "resumes")
    os.makedirs(resumes_dir, exist_ok=True)
    safe_label = _make_safe_label(file_label)
    date_str = datetime.now().strftime("%Y%m%d")

    # output_langs: 可选参数，指定输出语言子集。默认全部三种。
    global last_resume_md
    langs = output_langs if output_langs else ["en", "hk", "cn"]
    lang_results = {lang: {"resume_pdf": None, "resume_md": "", "cl_pdf": None, "cl_md": ""} for lang in langs}

    # ================================================================
    #  第一步：生成英文简历（主版本）
    # ================================================================
    emit(f"   📝 正在生成英文简历...")
    try:
        msg = llm_call(
            [{"role": "system", "content": system_content},
             {"role": "user", "content": user_content}],
        )
        lang_results["en"]["resume_md"] = _strip_code_block(msg.content)
        last_resume_md = lang_results["en"]["resume_md"]
    except Exception as e:
        return f"英文简历生成失败: {str(e)}"

    # ================================================================
    #  第二步：source_ids 事实核查
    # ================================================================
    en_resume_md = lang_results["en"]["resume_md"]
    check_report = []
    if en_resume_md:
        try:
            from checker import check_bullet
            from config import load_profile as _load_profile
            profile = _load_profile()
            if profile:
                parsed_bullets = _parse_source_ids_from_md(en_resume_md)
                for i, bullet in enumerate(parsed_bullets):
                    flags = check_bullet(bullet["source_ids"], profile, bullet["text"])
                    if flags:
                        check_report.append({
                            "bullet_index": i,
                            "text": bullet["text"][:120],
                            "source_ids": bullet["source_ids"],
                            "flags": flags,
                        })
                if check_report:
                    emit(f"   ⚠️ 事实核查发现 {len(check_report)} 条 bullet 存在问题")
                else:
                    emit(f"   ✅ 事实核查通过（{len(parsed_bullets)} 条 bullet 均无问题）")
                global last_check_report
                last_check_report = check_report
        except Exception as e:
            emit(f"   ⚠️ 事实核查跳过: {e}")
            last_check_report = []

    # ================================================================
    #  第三步：审查英文简历，不合格则重写
    # ================================================================
    review_dict = None
    review_summary = ""
    en_resume_md = lang_results["en"]["resume_md"]
    if en_resume_md:
        review_dict, review_summary = _review_resume(
            en_resume_md, file_label, resumes_dir, date_str)

        if review_dict and review_dict.get("overall_score", "A") in ("C", "D"):
            emit("   🔄 审查评分较低，正在根据反馈重新生成英文简历...")
            feedback = json.dumps(review_dict, ensure_ascii=False, indent=2)
            feedback_user = (
                f"{user_content}\n\n"
                f"====== 简历审查反馈（请根据以下反馈改进简历）======\n"
                f"{feedback}"
            )
            try:
                msg = llm_call(
                    [{"role": "system", "content": system_content},
                     {"role": "user", "content": feedback_user}],
                )
                lang_results["en"]["resume_md"] = _strip_code_block(msg.content)
                last_resume_md = lang_results["en"]["resume_md"]
                emit("   ✅ 英文简历已根据审查反馈重新生成")
            except Exception as e:
                emit(f"   ⚠️ 重新生成失败: {e}，使用原版简历")

    # 英文简历定稿，渲染 PDF
    en_resume_md = lang_results["en"]["resume_md"]
    resume_base = os.path.join(resumes_dir, f"resume_{safe_label}_{date_str}_en.md")
    lang_results["en"]["resume_pdf"] = render_pdf(_strip_ref_marks(en_resume_md), resume_base)
    if lang_results["en"]["resume_pdf"]:
        tag = " [已优化]" if review_dict and review_dict.get("overall_score", "A") in ("C", "D") else ""
        track_file(lang_results["en"]["resume_pdf"],
                   f"英文简历 PDF{tag} [{mode_label}] → {job_label}")

    # ================================================================
    #  第三步：生成英文 Cover Letter
    # ================================================================
    emit(f"   📨 正在生成英文 Cover Letter...")
    try:
        cl_msg = llm_call(
            [{"role": "system", "content": cl_prompt},
             {"role": "user", "content": user_content}],
        )
        lang_results["en"]["cl_md"] = _strip_code_block(cl_msg.content)
        cl_base = os.path.join(resumes_dir, f"cover_letter_{safe_label}_{date_str}_en.md")
        lang_results["en"]["cl_pdf"] = render_pdf(lang_results["en"]["cl_md"], cl_base)
        if lang_results["en"]["cl_pdf"]:
            track_file(lang_results["en"]["cl_pdf"],
                       f"英文 Cover Letter PDF [{mode_label}] → {job_label}")
    except Exception as e:
        emit(f"   ⚠️ 英文 Cover Letter 生成失败: {e}")

    # ================================================================
    #  第四步：将定稿英文版翻译为 hk/cn
    # ================================================================
    translate_resume_tpl = _load_resume_prompt("translate_resume_prompt")
    translate_cl_tpl = _load_resume_prompt("translate_cl_prompt")

    for lang in ["hk", "cn"]:
        lang_label = _LANG_LABELS[lang]
        target_lang = _TRANSLATE_LANG_NAMES[lang]

        # 翻译简历
        if en_resume_md:
            emit(f"   🌐 正在翻译简历为{lang_label}...")
            translate_sys = render_prompt(translate_resume_tpl, target_lang=target_lang)
            try:
                msg = llm_call(
                    [{"role": "system", "content": translate_sys},
                     {"role": "user", "content": en_resume_md}],
                )
                lang_results[lang]["resume_md"] = _strip_code_block(msg.content)
                resume_base = os.path.join(
                    resumes_dir, f"resume_{safe_label}_{date_str}_{lang}.md")
                lang_results[lang]["resume_pdf"] = render_pdf(_strip_ref_marks(lang_results[lang]["resume_md"]), resume_base)
                if lang_results[lang]["resume_pdf"]:
                    track_file(lang_results[lang]["resume_pdf"],
                               f"{lang_label}简历 PDF [{mode_label}] → {job_label}")
            except Exception as e:
                emit(f"   ⚠️ {lang_label}简历翻译失败: {e}")

        # 翻译 Cover Letter
        en_cl_md = lang_results["en"].get("cl_md", "")
        if en_cl_md:
            emit(f"   🌐 正在翻译 Cover Letter 为{lang_label}...")
            translate_cl_sys = render_prompt(translate_cl_tpl, target_lang=target_lang)
            try:
                msg = llm_call(
                    [{"role": "system", "content": translate_cl_sys},
                     {"role": "user", "content": en_cl_md}],
                )
                lang_results[lang]["cl_md"] = _strip_code_block(msg.content)
                cl_base = os.path.join(
                    resumes_dir, f"cover_letter_{safe_label}_{date_str}_{lang}.md")
                lang_results[lang]["cl_pdf"] = render_pdf(lang_results[lang]["cl_md"], cl_base)
                if lang_results[lang]["cl_pdf"]:
                    track_file(lang_results[lang]["cl_pdf"],
                               f"{lang_label} Cover Letter PDF [{mode_label}] → {job_label}")
            except Exception as e:
                emit(f"   ⚠️ {lang_label} Cover Letter 翻译失败: {e}")

    # ================================================================
    #  构建返回信息
    # ================================================================
    result = f"✅ 三语简历 + Cover Letter 已生成！（{mode_label}模式）\n"
    result += f"   目标: {job_label}\n"
    if company:
        result += f"   公司: {company}\n"
    result += f"\n"

    for lang in langs:
        lang_label = _LANG_LABELS[lang]
        lr = lang_results.get(lang, {})

        if not lr.get("resume_pdf"):
            result += f"   ⚠️ {lang_label}简历 PDF 生成失败\n\n"
            continue

        result += f"   🌐 {lang_label}版:\n"
        result += f"      📄 简历:        {lr['resume_pdf']}\n"
        if lr.get("cl_pdf"):
            result += f"      📨 Cover Letter: {lr['cl_pdf']}\n"
        else:
            result += f"      ⚠️ Cover Letter 生成失败\n"
        result += f"\n"

    en_lr = lang_results.get("en", {})
    if en_lr.get("resume_md"):
        result += f"--- 英文简历预览 ---\n{en_lr['resume_md'][:2000]}\n"
        if len(en_lr["resume_md"]) > 2000:
            result += f"...（完整内容请查看文件）\n"

    if en_lr.get("cl_md"):
        result += f"\n--- 英文 Cover Letter 预览 ---\n{en_lr['cl_md'][:1000]}\n"
        if len(en_lr["cl_md"]) > 1000:
            result += f"...（完整内容请查看文件）\n"

    if review_summary:
        result += review_summary

    return result

# ============================================================
#  source_ids 标记解析与剥离
# ============================================================

import re as _re

_REF_PATTERN = _re.compile(r'\s*\[ref:\s*([^\]]+)\]')

def _parse_source_ids_from_md(md_text: str) -> list[dict]:
    """
    从带 [ref: ...] 标记的 Markdown 中，逐条提取 bullet 和 source_ids。

    Returns: [
        {"text": "bullet 原文（已剥离标记）", "source_ids": ["dep_001"], "raw": "原始行"},
        ...
    ]
    """
    results = []
    for line in md_text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('- '):
            m = _REF_PATTERN.search(line)
            source_ids = []
            text = line
            if m:
                raw_ids = m.group(1)
                source_ids = [sid.strip() for sid in raw_ids.split(',') if sid.strip()]
                text = line[:m.start()] + line[m.end():]
                text = text.rstrip()
            results.append({
                "text": text.lstrip('- ').strip(),
                "source_ids": source_ids,
                "raw": line,
            })
    return results

def _strip_ref_marks(md_text: str) -> str:
    """从 Markdown 中移除所有 [ref: ...] 标记，用于 PDF 渲染。"""
    return _REF_PATTERN.sub('', md_text)

# ============================================================
#  定点修补：对单条 bullet 做 LLM 重写
# ============================================================

def fix_single_bullet(
    original_md: str,
    bullet_index: int,
    user_feedback: str,
    profile: dict = None,
    template_config: dict = None,
    guide_config: dict = None,
) -> str:
    """
    对简历中的单条 bullet 做定点修补。

    Args:
        original_md: 原始简历 Markdown 全文
        bullet_index: 要修补的 bullet 序号（从 0 开始）
        user_feedback: 用户反馈或修正指令
        profile: 用户画像（用于重新核查）
        template_config: 简历模板配置
        guide_config: 简历撰写指南

    Returns:
        修补后的完整 Markdown 文本（失败时返回原文本）
    """
    import re as _re_fix

    # ── 解析出所有 bullet ──
    parsed = _parse_source_ids_from_md(original_md)
    if bullet_index < 0 or bullet_index >= len(parsed):
        return original_md

    target = parsed[bullet_index]
    original_bullet_text = target["text"]
    original_raw_line = target["raw"]

    # ── 构造修补 prompt ──
    fix_prompt = f"""你是一个专业的简历修改助手。以下是已生成的简历全文。

请只修改第 {bullet_index + 1} 条 bullet（从 1 开始计数）：
原文本：{original_bullet_text}

修改要求：{user_feedback}

规则：
1. 只修改这一条 bullet，其他所有内容（Summary、Skills、其他 bullet、Education 等）保持完全不变。
2. 修改后的 bullet 仍然要符合简历的写作风格（业务成果导向、量化、动词开头）。
3. 如果原 bullet 有 [ref: ...] 标记，保留或更新标记。
4. 直接输出修改后的完整简历 Markdown，不要输出任何解释或代码块包裹。

--- 简历全文 ---
{original_md}"""

    # ── 调用 LLM 修补 ──
    try:
        msg = llm_call(
            [{"role": "user", "content": fix_prompt}],
            temperature=0.3,
            thinking={"type": "disabled"},
        )
        fixed_md = msg.content or ""
        fixed_md = _strip_code_block(fixed_md)
    except Exception:
        return original_md

    # ── 验证：解析修补后的 bullet ──
    fixed_parsed = _parse_source_ids_from_md(fixed_md)
    if len(fixed_parsed) != len(parsed):
        # bullet 数量变了，拒绝修补结果
        return original_md

    # ── 检查非目标 bullet 是否保持不变 ──
    for i, (orig, fixed) in enumerate(zip(parsed, fixed_parsed)):
        if i != bullet_index:
            if orig["text"] != fixed["text"]:
                return original_md  # 其他 bullet 被改了，拒绝

    # ── 重新核查修补后的 bullet ──
    if profile:
        try:
            from checker import check_bullet as _check
            new_flags = _check(fixed_parsed[bullet_index]["source_ids"], profile,
                               fixed_parsed[bullet_index]["text"])
            if new_flags:
                # 仍然有问题，再试一次
                retry_feedback = f"仍然存在问题（{', '.join(new_flags)}）。请再次修正：{user_feedback}"
                retry_prompt = f"""你是一个专业的简历修改助手。以下是已生成的简历全文。

第 {bullet_index + 1} 条 bullet 修改后仍然有问题：
当前文本：{fixed_parsed[bullet_index]['text']}
问题：{', '.join(new_flags)}

修改要求：{retry_feedback}

规则：只修改这一条 bullet。直接输出修改后的完整简历 Markdown。

--- 简历全文 ---
{fixed_md}"""
                try:
                    msg2 = llm_call(
                        [{"role": "user", "content": retry_prompt}],
                        temperature=0.3,
                        thinking={"type": "disabled"},
                    )
                    fixed_md = msg2.content or ""
                    fixed_md = _strip_code_block(fixed_md)
                except Exception:
                    pass  # retry failed, return first attempt
        except Exception:
            pass  # checker unavailable, return as-is

    return fixed_md
