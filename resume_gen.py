"""
resume_gen.py - 多模式简历生成（三语 PDF）

支持 5 种输入模式：
  1. by_direction — 基于匹配数据按方向批量生成（需先 search + match）
  2. job_index    — 基于匹配排名中的岗位（需先 search + match）
  3. jd_text      — 基于用户粘贴的任意 JD 文本
  4. role_direction — 基于岗位方向/角色类型（如 "Solutions Engineer"）
  5. 无参数       — 基于用户画像生成通用简历
"""
import os
import json
import yaml
from datetime import datetime

import config
from config import (
    emit, client, OUTPUT_DIR, track_file,
    load_profile, load_yaml, load_search_config_dict, parse_json_response,
    get_current_run_dir, get_latest_run_dir,
    load_prompts, render_prompt,
)
from pdf_renderer import render_resume as render_pdf
from job_match import classify_job, get_weights


# ============================================================
#  各模式的 LLM 系统 prompt
# ============================================================

_BASE_RULES = """核心规则：
1. 只使用候选人档案中的真实信息，绝对不能编造
2. 输出 Markdown 格式，严格控制在1-2页
3. 简历语言用英文
4. 不要放照片、不要个人身份信息（年龄、婚姻状况、身份证号等）
5. 使用标准段落标题：Summary, Skills, Work Experience, Education, Certifications
6. 工作经历每个角色最多4个要点，每个要点必须用 "- " 开头（markdown 无序列表），用「动词+做了什么+量化结果」格式
7. 不要大段文字描述，所有要点必须是独立的 "- " 开头的 bullet points，禁止写成连续段落
8. Skills 按类别分组（Languages, Frameworks, Tools 等），每组不超过6项
9. Summary 最多3句话，体现核心竞争力+经验年限+目标方向

简历撰写指南：
<guide>"""

_PROMPT_FOR_JOB = """你是一个专业简历撰写专家。根据候选人档案和目标岗位，生成一份定制化的英文简历。

简历模板配置：
<template>

<base_rules>
5. 根据目标岗位的 JD 要求调整技能展示顺序，最相关的放前面
6. Summary 部分要直接呼应 JD 中的关键要求
7. 工作经历优先展示与目标岗位相关的成果和技术栈
8. 如果匹配分析中提到了候选人的优势技能，在简历中突出展示
9. 如果匹配分析中提到了缺失技能，考虑在相关经验中补充可迁移技能"""

_PROMPT_FOR_JD_TEXT = """你是一个专业简历撰写专家。用户提供了一段职位描述（JD），请根据候选人档案和这份 JD 生成一份定制化的英文简历。

简历模板配置：
<template>

<base_rules>
5. 仔细分析 JD 中要求的技能、经验和职责
6. 调整技能展示顺序，让 JD 中提到的关键技能排在前面
7. Summary 部分要直接呼应 JD 中的核心要求
8. 工作经历的 bullet points 优先展示与 JD 相关的成果
9. 如果 JD 要求的某些技能候选人不直接具备，尝试展示可迁移的相关技能"""

_PROMPT_FOR_ROLE = """你是一个专业简历撰写专家。用户想生成一份面向「<role>」方向的简历。
请根据你对这个角色的理解（通常需要什么技能、什么经验、什么素质），结合候选人档案，生成一份针对性的英文简历。

简历模板配置：
<template>

<base_rules>
5. 先分析「<role>」这个角色通常需要什么：核心技能、软技能、行业知识、工作职责
6. 然后从候选人档案中挑选最匹配的经验和技能，重新组织展示
7. Summary 要体现候选人为什么适合这个方向
8. 工作经历优先展示与该方向相关的成果，弱化不相关的内容"""

_PROMPT_FOR_GENERAL = """你是一个专业简历撰写专家。请根据候选人档案生成一份通用英文简历，突出候选人最强的竞争力。

简历模板配置：
<template>

<base_rules>
5. 参考候选人的求职意向（target_titles），让简历的定位与意向方向一致
6. Summary 要综合体现候选人的技术能力和业务能力
7. 技能排列按照候选人的核心优势排序，而非按字母顺序
8. 工作经历全面展示，但用 bullet points 突出最有影响力的成果"""


# ============================================================
#  Cover Letter prompt
# ============================================================

_COVER_LETTER_PROMPT = """你是一个专业求职信撰写专家。请根据候选人档案和目标岗位信息，生成一封专业的英文 Cover Letter。

写作规则：
1. 只使用候选人档案中的真实信息，绝对不能编造
2. 输出 Markdown 格式
3. 语言用英文
4. 长度控制在一页以内（约 250-350 词）
5. 结构清晰：开头（申请意图）→ 中间（核心匹配点 2-3 个）→ 结尾（期待沟通）

内容要求：
- 开头：简明说明申请什么岗位、从什么渠道了解到该机会、一句话的自我定位
- 中间段落：从候选人经历中挑选 2-3 个与该岗位最相关的亮点，具体说明为什么匹配
  - 不要笼统地罗列技能，要结合实际项目和成果来论证
  - 如果知道公司信息，体现对公司业务的理解
- 结尾：表达期待进一步沟通的意愿，语气专业但不卑不亢
- 署名用候选人的英文名

语气要求：
- 专业、自信但不傲慢
- 避免模板化套话（如 "I am writing to express my interest..."）
- 开头要有吸引力，让 hiring manager 愿意继续读下去"""


# ============================================================
#  方向聚合分析 prompt
# ============================================================

_AGGREGATE_SYSTEM_PROMPT = """你是一位资深求职策略顾问。以下是候选人画像和某个方向下多个达标岗位的完整 JD。
请分析这些 JD 的共性要求，并与候选人画像做交叉比对。

候选人画像摘要：
<profile_summary>

技能分类规则（非常重要）：
- direct_match：候选人画像中明确具备的技能 → 简历重点展示
- quick_learnable：候选人不直接具备，但属于通用开发技术栈（如 Kafka、K8s、RabbitMQ、Redis Cluster 等），
  且候选人有相近技能基础可以快速上手 → 简历中列出但不标精通，Cover Letter 中表态
- hard_gap：需要专门培训或完全不相关的领域（如深度学习、iOS 开发、Solidity 审计等）→ 简历不提

输出严格的 JSON，不要输出其他文字：
{
  "direction": "方向名称",
  "job_count": 岗位数量,
  "common_requirements": {
    "direct_match": [
      {"skill": "Python", "frequency": "80%", "candidate_level": "精通"}
    ],
    "quick_learnable": [
      {"skill": "Kafka", "frequency": "60%", "related_skill": "候选人有 RabbitMQ 经验", "reason": "消息队列原理相通，上手快"}
    ],
    "hard_gap": [
      {"skill": "Solidity审计", "frequency": "40%", "reason": "需要专门培训，非通用开发技能"}
    ]
  },
  "typical_responsibilities": ["最常见的3-5条岗位职责"],
  "common_bonus": ["常见加分项，如语言能力、认证、行业经验等"],
  "resume_strategy": "一段针对该方向的简历撰写策略建议（100字以内）"
}"""


_PROMPT_FOR_DIRECTION_DATA = """你是一个专业简历撰写专家。请根据候选人档案和该方向的市场需求聚合数据，生成一份面向「<direction>」方向的英文简历。

这份简历将用于批量投递该方向的岗位，所以要覆盖该方向的共性需求，而非针对某一家公司。

简历模板配置：
<template>

<base_rules>

市场数据驱动的特殊规则（优先级高于基础规则）：
1. Skills 展示顺序：先列 direct_match 技能（标注熟练度），再列 quick_learnable 技能（不标精通），不出现 hard_gap 技能
2. quick_learnable 技能只在 Skills 区列出名称，不在工作经历中虚构使用场景
3. Summary 要呼应该方向的 typical_responsibilities，展示候选人为什么适合这个方向
4. 工作经历的 bullet points 优先展示与该方向 common_requirements 中 direct_match 技能相关的成果
5. 如果 common_bonus 中有候选人具备的加分项（语言、认证等），确保在简历中体现"""


_CL_FOR_DIRECTION_DATA = """你是一个专业求职信撰写专家。请根据候选人档案和该方向的市场需求聚合数据，生成一封面向「<direction>」方向的英文 Cover Letter。

这封 Cover Letter 将用于批量投递，所以不要提及具体公司名称，用 "your team" / "your company" 代替。

写作规则：
1. 只使用候选人档案中的真实信息，绝对不能编造
2. 输出 Markdown 格式
3. 语言用英文
4. 长度控制在一页以内（约 250-350 词）
5. 结构：开头（方向定位 + 自我介绍）→ 中间（2-3 个与该方向最匹配的亮点）→ 结尾（期待沟通）

市场数据驱动的特殊规则：
- 中间段落围绕 direct_match 技能展开，用实际项目成果论证
- 对 quick_learnable 中的关键技能，用一句话表达学习意愿和相近基础（如 "With hands-on experience in RabbitMQ, I'm well-positioned to quickly adopt Kafka"）
- 不要提及 hard_gap 技能
- 如果聚合数据中有 common_bonus 候选人具备的，在信中自然提及

语气：专业、自信，避免模板化套话。"""


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

    prompts = load_prompts()
    template = prompts.get("resume", {}).get(
        "aggregate_system_prompt", _AGGREGATE_SYSTEM_PROMPT)

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
            resp = client.chat.completions.create(
                model=config.MODEL_NAME,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"方向：{direction}\n\n以下是该方向 {len(jobs)} 个达标岗位的 JD：\n{jds_text}"}
                ]
            )
            parsed = parse_json_response(resp.choices[0].message.content)
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


def _generate_for_direction_batch(profile, profile_text, template_text, base_rules, resume_prompts):
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

    search_cfg, _ = load_search_config_dict()
    search_cfg = search_cfg or {}

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
            resume_prompts.get("prompt_for_direction_data", _PROMPT_FOR_DIRECTION_DATA),
            direction=direction, template=template_text, base_rules=base_rules)

        user_content = (
            f"候选人完整档案：\n{profile_text}\n\n"
            f"「{direction}」方向市场需求聚合数据：\n{agg_text}\n\n"
            f"请根据以上信息生成一份面向 {direction} 方向的简历。"
        )

        cl_prompt = render_prompt(
            resume_prompts.get("cl_for_direction_data", _CL_FOR_DIRECTION_DATA),
            direction=direction)

        result = _call_llm_and_save(
            system_content, user_content, direction,
            mode_label="方向聚合", job_label=f"{direction} 方向（基于 {agg_data.get('job_count', '?')} 个岗位）",
            cl_prompt=cl_prompt)
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

def generate_resume(job_index=None, jd_text=None, role_direction=None, by_direction=False):
    """
    多模式简历生成。根据传入参数自动选择模式：
      - by_direction: 基于匹配数据按方向批量生成（需先 search + match）
      - job_index: 基于匹配排名中的岗位
      - jd_text: 基于用户粘贴的 JD 文本
      - role_direction: 基于岗位方向（如 "Solutions Engineer"）
      - 均为空: 生成通用简历
    """
    # ── 加载公共资源 ──
    profile, err = load_profile()
    if err:
        return err

    template_config, _ = load_yaml("resume_template.yaml")
    template_config = template_config or {}

    guide_config, _ = load_yaml("resume_guide.yaml")
    guide_text = yaml.dump(guide_config, allow_unicode=True, default_flow_style=False) if guide_config else ""

    profile_text = yaml.dump(profile, allow_unicode=True, default_flow_style=False)
    template_text = yaml.dump(template_config, allow_unicode=True, default_flow_style=False)

    # ── 加载 YAML prompt（优先 prompts.yaml，缺失时回退硬编码默认值） ──
    resume_prompts = load_prompts().get("resume", {})

    # 将指南注入 base_rules
    base_rules_template = resume_prompts.get("base_rules", _BASE_RULES)
    base_rules = render_prompt(base_rules_template, guide=guide_text)

    if by_direction:
        return _generate_for_direction_batch(
            profile, profile_text, template_text, base_rules, resume_prompts)
    elif job_index is not None:
        return _generate_for_matched_job(
            job_index, profile, profile_text, template_text, base_rules, resume_prompts)
    elif jd_text:
        return _generate_for_jd_text(
            jd_text, profile_text, template_text, base_rules, resume_prompts)
    elif role_direction:
        return _generate_for_role(
            role_direction, profile_text, template_text, base_rules, resume_prompts)
    else:
        return _generate_general(
            profile, profile_text, template_text, base_rules, resume_prompts)


# ============================================================
#  模式 1：基于匹配岗位
# ============================================================

def _generate_for_matched_job(job_index, profile, profile_text, template_text, base_rules, resume_prompts):
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
        resume_prompts.get("prompt_for_job", _PROMPT_FOR_JOB),
        template=template_text, base_rules=base_rules)
    user_content = f"候选人完整档案：\n{profile_text}\n\n目标岗位（含匹配分析）：\n{job_text}\n\n请生成定制简历。"
    file_label = job_label
    company = target_job.get("company", "")

    return _call_llm_and_save(
        system_content, user_content, file_label,
        mode_label="匹配岗位", job_label=job_label, company=company,
        cl_prompt=resume_prompts.get("cover_letter_prompt", _COVER_LETTER_PROMPT))


# ============================================================
#  模式 2：基于 JD 文本
# ============================================================

def _generate_for_jd_text(jd_text, profile_text, template_text, base_rules, resume_prompts):
    """基于用户粘贴的 JD 文本生成定制简历"""
    # 尝试从 JD 中提取岗位名称
    first_line = jd_text.strip().split("\n")[0][:80]
    job_label = first_line if len(first_line) > 3 else "自定义JD"

    emit(f"   📝 模式: JD 文本 | 正在根据粘贴的 JD 生成定制简历...")

    system_content = render_prompt(
        resume_prompts.get("prompt_for_jd_text", _PROMPT_FOR_JD_TEXT),
        template=template_text, base_rules=base_rules)
    user_content = f"候选人完整档案：\n{profile_text}\n\n目标岗位 JD：\n{jd_text}\n\n请生成定制简历。"

    return _call_llm_and_save(
        system_content, user_content, job_label,
        mode_label="JD 文本", job_label=job_label,
        cl_prompt=resume_prompts.get("cover_letter_prompt", _COVER_LETTER_PROMPT))


# ============================================================
#  模式 3：基于岗位方向
# ============================================================

def _generate_for_role(role_direction, profile_text, template_text, base_rules, resume_prompts):
    """基于岗位方向/角色类型生成针对性简历"""
    emit(f"   📝 模式: 岗位方向 | 正在生成「{role_direction}」方向的简历...")

    system_content = render_prompt(
        resume_prompts.get("prompt_for_role", _PROMPT_FOR_ROLE),
        role=role_direction, template=template_text, base_rules=base_rules)
    user_content = f"候选人完整档案：\n{profile_text}\n\n请生成一份面向「{role_direction}」方向的简历。"

    return _call_llm_and_save(
        system_content, user_content, role_direction,
        mode_label="岗位方向", job_label=f"{role_direction} 方向",
        cl_prompt=resume_prompts.get("cover_letter_prompt", _COVER_LETTER_PROMPT))


# ============================================================
#  模式 4：通用简历
# ============================================================

def _generate_general(profile, profile_text, template_text, base_rules, resume_prompts):
    """基于用户画像生成通用简历"""
    intent = profile.get("job_intent", {})
    directions = ", ".join(intent.get("target_titles", [])[:3])

    emit(f"   📝 模式: 通用简历 | 正在生成通用版简历...")

    system_content = render_prompt(
        resume_prompts.get("prompt_for_general", _PROMPT_FOR_GENERAL),
        template=template_text, base_rules=base_rules)
    user_content = f"候选人完整档案：\n{profile_text}\n\n请生成一份通用简历，定位方向参考：{directions}。"

    return _call_llm_and_save(
        system_content, user_content, "general",
        mode_label="通用", job_label="通用简历",
        cl_prompt=resume_prompts.get("cover_letter_prompt", _COVER_LETTER_PROMPT))


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
    review_prompt = load_prompts().get("resume", {}).get("resume_review_prompt")
    if not review_prompt:
        return None, ""

    emit("   🔍 正在审查英文简历质量...")

    try:
        resp = client.chat.completions.create(
            model=config.MODEL_NAME,
            temperature=0,
            messages=[
                {"role": "system", "content": review_prompt},
                {"role": "user", "content": resume_md}
            ]
        )
        review = parse_json_response(resp.choices[0].message.content)

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


_TRANSLATE_RESUME_PROMPT = """你是一位专业的简历翻译专家。请将以下英文简历精确翻译为<target_lang>。

翻译规则：
1. 保持完全一致的结构、段落顺序和 bullet points 数量
2. 保持 Markdown 格式不变
3. 技术术语（编程语言、框架、工具名称）保留英文原文，不翻译
4. 公司名称保留英文，可在括号内加中文（如已知）
5. 学历、证书名称保留英文，可在括号内加中文
6. 数字和量化指标保持不变
7. 语气和专业度与英文版一致"""

_TRANSLATE_CL_PROMPT = """你是一位专业的求职信翻译专家。请将以下英文 Cover Letter 精确翻译为<target_lang>。

翻译规则：
1. 保持完全一致的段落结构和论述逻辑
2. 保持 Markdown 格式不变
3. 技术术语保留英文原文
4. 公司名称保留英文
5. 语气专业自信，符合<target_lang>的商务写作习惯
6. 署名保留英文名"""

_TRANSLATE_LANG_NAMES = {"hk": "繁體中文（香港用語）", "cn": "简体中文"}


def _call_llm_and_save(system_content, user_content, file_label,
                       mode_label="", job_label="", company="",
                       cl_prompt=None):
    """英文先行 → 审查 → 定稿 → 翻译到其他语言"""
    run_dir = get_current_run_dir() or get_latest_run_dir()
    if run_dir:
        resumes_dir = os.path.join(run_dir, "resumes")
    else:
        resumes_dir = os.path.join(OUTPUT_DIR, "resumes")
    os.makedirs(resumes_dir, exist_ok=True)
    safe_label = _make_safe_label(file_label)
    date_str = datetime.now().strftime("%Y%m%d")

    langs = ["en", "hk", "cn"]
    lang_results = {lang: {"resume_pdf": None, "resume_md": "", "cl_pdf": None, "cl_md": ""} for lang in langs}

    # ================================================================
    #  第一步：生成英文简历（主版本）
    # ================================================================
    emit(f"   📝 正在生成英文简历...")
    try:
        resp = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ]
        )
        lang_results["en"]["resume_md"] = _strip_code_block(resp.choices[0].message.content)
    except Exception as e:
        return f"英文简历生成失败: {str(e)}"

    # ================================================================
    #  第二步：审查英文简历，不合格则重写
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
                resp = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": feedback_user}
                    ]
                )
                lang_results["en"]["resume_md"] = _strip_code_block(resp.choices[0].message.content)
                emit("   ✅ 英文简历已根据审查反馈重新生成")
            except Exception as e:
                emit(f"   ⚠️ 重新生成失败: {e}，使用原版简历")

    # 英文简历定稿，渲染 PDF
    en_resume_md = lang_results["en"]["resume_md"]
    resume_base = os.path.join(resumes_dir, f"resume_{safe_label}_{date_str}_en.md")
    lang_results["en"]["resume_pdf"] = render_pdf(en_resume_md, resume_base)
    if lang_results["en"]["resume_pdf"]:
        tag = " [已优化]" if review_dict and review_dict.get("overall_score", "A") in ("C", "D") else ""
        track_file(lang_results["en"]["resume_pdf"],
                   f"英文简历 PDF{tag} [{mode_label}] → {job_label}")

    # ================================================================
    #  第三步：生成英文 Cover Letter
    # ================================================================
    emit(f"   📨 正在生成英文 Cover Letter...")
    try:
        cl_resp = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": cl_prompt or _COVER_LETTER_PROMPT},
                {"role": "user", "content": user_content}
            ]
        )
        lang_results["en"]["cl_md"] = _strip_code_block(cl_resp.choices[0].message.content)
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
    resume_prompts = load_prompts().get("resume", {})
    translate_resume_tpl = resume_prompts.get("translate_resume_prompt", _TRANSLATE_RESUME_PROMPT)
    translate_cl_tpl = resume_prompts.get("translate_cl_prompt", _TRANSLATE_CL_PROMPT)

    for lang in ["hk", "cn"]:
        lang_label = _LANG_LABELS[lang]
        target_lang = _TRANSLATE_LANG_NAMES[lang]

        # 翻译简历
        if en_resume_md:
            emit(f"   🌐 正在翻译简历为{lang_label}...")
            translate_sys = render_prompt(translate_resume_tpl, target_lang=target_lang)
            try:
                resp = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": translate_sys},
                        {"role": "user", "content": en_resume_md}
                    ]
                )
                lang_results[lang]["resume_md"] = _strip_code_block(resp.choices[0].message.content)
                resume_base = os.path.join(
                    resumes_dir, f"resume_{safe_label}_{date_str}_{lang}.md")
                lang_results[lang]["resume_pdf"] = render_pdf(lang_results[lang]["resume_md"], resume_base)
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
                resp = client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": translate_cl_sys},
                        {"role": "user", "content": en_cl_md}
                    ]
                )
                lang_results[lang]["cl_md"] = _strip_code_block(resp.choices[0].message.content)
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
