"""
eval_core.py — 评估公共核心模块

Web UI (_run_eval_sse) 调用的评估逻辑。
提供 load_eval_dataset / build_eval_jobs_list / is_placeholder_profile /
compute_metrics / compare_with_history / cleanup_old_results /
run_evaluation 七个函数。
"""
import json
import os
import re
from datetime import datetime
from collections import Counter

from config import emit, OUTPUT_DIR
from config import clear_usage_accumulator, get_accumulated_usage
from config import load_search_config_dict


# ============================================================
#  价格常量（单位：USD / 1M tokens）
# ============================================================

PRICES = {
    "deepseek": {"input": 0.55, "output": 2.19},
    "deepseek-v4-pro": {"input": 0.55, "output": 2.19},
    "qwen": {"input": 0.40, "output": 1.60},
    "qwen3.6-plus": {"input": 0.40, "output": 1.60},
    "glm": {"input": 1.00, "output": 1.50},
    "glm-5.1": {"input": 1.00, "output": 1.50},
}


# ============================================================
#  工具函数
# ============================================================

def _load_model_name() -> str:
    """从 search_config 读取当前模型名。"""
    try:
        cfg, _ = load_search_config_dict()
        return (cfg or {}).get("llm", {}).get("model", "unknown")
    except Exception:
        return "unknown"


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算单次调用的美元成本。"""
    price = PRICES.get(model, PRICES["deepseek-v4-pro"])
    return (input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"]


def is_placeholder_profile(profile: dict) -> bool:
    """判断用户画像是否实质有内容。

    返回 True 表示是空模板，False 表示有实质内容。
    """
    if not profile:
        return True
    score = 0

    # 1. 工作经历：有实质描述
    work = profile.get("work_experience", [])
    if work and len(work) > 0:
        first = work[0]
        if first.get("description") or first.get("highlights") or first.get("core_modules"):
            score += 3
        elif first.get("company") and first.get("title"):
            score += 1

    # 2. 技能：有多个类别或具体条目
    skills = profile.get("skills", {})
    skill_count = 0
    for category, items in skills.items():
        if isinstance(items, list) and len(items) > 0:
            skill_count += len(items)
    if skill_count >= 5:
        score += 3
    elif skill_count >= 2:
        score += 2
    elif skill_count >= 1:
        score += 1

    # 3. 项目经历：有实质描述
    projects = profile.get("projects", [])
    if projects and len(projects) > 0:
        if any(p.get("description") or p.get("resume_bullets") for p in projects):
            score += 2

    # 4. 自我评价：有足够长度的描述
    summary = profile.get("summary", "")
    if summary and len(summary.strip()) > 50:
        score += 1

    # 判定：总分 >= 3 认为画像有实质内容
    return score < 3


# ============================================================
#  1. 加载数据集
# ============================================================

def load_eval_dataset(set_name: str) -> list:
    """从 instances/eval/{set_name}.json 加载标注数据集。"""
    input_path = os.path.join("instances", "eval", f"{set_name}.json")
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
#  2. 构建 jobs_list
# ============================================================

def build_eval_jobs_list(cases: list) -> list:
    """补全 url/location/salary 等字段，构建 execute_matching_pipeline 所需输入。"""
    jobs_list = []
    for i, case in enumerate(cases):
        jobs_list.append({
            "eval_id": case["id"],
            "title": case["title"],
            "company": case.get("company", "评估测试"),
            "url": case.get("url", ""),
            "location": case.get("location", "未知"),
            "salary": case.get("salary", "未知"),
            "description": case["description"],
            "index": i + 1,
        })
    return jobs_list


# ============================================================
#  3. 构建方向混淆矩阵
# ============================================================

def build_confusion_matrix(results: list) -> dict:
    """从 results 列表构建方向混淆矩阵。

    Returns:
        {
            "labels": ["default", "payment", ...],
            "matrix": [[8, 0, 1, ...], ...]
            # matrix[i][j] = expected=labels[i] 被预测为 labels[j] 的数量
        }
    """
    all_dirs = set()
    for r in results:
        all_dirs.add(r["expected_direction"])
        all_dirs.add(r["predicted_direction"])
    labels = sorted(all_dirs)

    idx = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]

    for r in results:
        i = idx[r["expected_direction"]]
        j = idx[r["predicted_direction"]]
        matrix[i][j] += 1

    return {"labels": labels, "matrix": matrix}


# ============================================================
#  4. 计算评估指标
# ============================================================

def _calc_ranking_consistency(results: list) -> float | None:
    """计算 LLM 打分排序与 expected_tier 期望排序的一致性。

    对有效条目（tier_correct is not None）的所有 pair，比较
    LLM total_score 排序方向与 expected_tier 数值排序方向是否一致。
    有效条目 < 2 时返回 None。
    """
    TIER_MAP = {"High": 3, "Medium": 2, "Low": 1}
    valid = [r for r in results if r.get("tier_correct") is not None]
    if len(valid) < 2:
        return None

    concordant = 0
    total_pairs = 0

    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            total_pairs += 1
            si, sj = valid[i]["total_score"], valid[j]["total_score"]
            ti = TIER_MAP.get(valid[i].get("expected_tier", ""), 0)
            tj = TIER_MAP.get(valid[j].get("expected_tier", ""), 0)

            llm_dir = 1 if si > sj else (-1 if si < sj else 0)
            tier_dir = 1 if ti > tj else (-1 if ti < tj else 0)

            if llm_dir == 0 or tier_dir == 0:
                concordant += 0.5
            elif llm_dir == tier_dir:
                concordant += 1

    return concordant / total_pairs if total_pairs > 0 else None


def compute_metrics(cases: list, all_scored: list, profile_summary: str,
                    direction_results: list | None = None) -> dict:
    """将 direction_results 作为主表，all_scored 通过 eval_id LEFT JOIN。

    遍历全量方向结果，去评分结果中查找对应分数。
    找到评分 → 合并方向和分数；找不到 → 方向取 Step 1 结果，分数填 0。
    """
    scored_dict = {s["eval_id"]: s for s in all_scored if s.get("eval_id")}
    case_dict = {c["id"]: c for c in cases}

    results = []
    errors = 0

    # 主表 = direction_results（Step 1 全量结果），LEFT JOIN all_scored
    for dr in (direction_results or []):
        eid = dr.get("eval_id", "")
        case = case_dict.get(eid)
        if not case:
            continue  # 跳过不属于评估数据集的条目

        scored = scored_dict.get(eid)
        if scored:
            predicted_dir = dr.get("llm_direction", "default")
            scores = scored.get("scores", {})
            total_score = scored.get("total_score", 0)
            reason = scored.get("reason", "")
        else:
            predicted_dir = dr.get("llm_direction", "default")
            scores = {}
            total_score = 0
            reason = "评分缺失，方向来自 Step 1 分类"
            errors += 1

        expected_dir = case.get("expected_direction", "default")
        match = "✓" if predicted_dir == expected_dir else f"✗ (expected {expected_dir})"
        emit(f"[{case['id']}] {case['title'][:60]} → {predicted_dir} {match}")

        # ── 分数档位准确率 ──
        expected_tier = case.get("expected_tier", "")
        if expected_tier in ("High", "Medium", "Low"):
            tier_correct = (
                (expected_tier == "High"   and total_score >= 70) or
                (expected_tier == "Medium" and 45 <= total_score <= 69) or
                (expected_tier == "Low"    and total_score < 45)
            )
        else:
            tier_correct = None

        results.append({
            "id": case["id"],
            "title": case["title"],
            "company": case.get("company", ""),
            "url": case.get("url", ""),
            "expected_direction": expected_dir,
            "predicted_direction": predicted_dir,
            "direction_source": dr.get("direction_source", "unknown"),
            "direction_correct": predicted_dir == expected_dir,
            "scores": scores,
            "total_score": total_score,
            "reason": reason,
            # ── 离线分析支撑字段 ──
            "description": case["description"],
            "profile_summary": profile_summary,
            # ── 分数档位 ──
            "expected_tier": expected_tier,
            "tier_correct": tier_correct,
        })

    # 方向准确率
    dir_correct = sum(1 for r in results if r.get("direction_correct"))
    dir_total = len(results)
    dir_accuracy = dir_correct / dir_total if dir_total > 0 else 0

    # 按方向分别统计
    dir_counts = Counter()
    dir_hits = Counter()
    for r in results:
        d = r["expected_direction"]
        dir_counts[d] += 1
        if r.get("direction_correct"):
            dir_hits[d] += 1

    # 混淆矩阵
    confusion_matrix = build_confusion_matrix(results)

    # 分档准确率（仅统计有效标注）
    tier_valid = [r for r in results if r.get("tier_correct") is not None]
    tier_correct_n = sum(1 for r in tier_valid if r["tier_correct"])
    tier_accuracy = tier_correct_n / len(tier_valid) if tier_valid else None

    # 排序一致性
    ranking_consistency = _calc_ranking_consistency(results)

    return {
        "results": results,
        "dir_correct": dir_correct,
        "dir_total": dir_total,
        "dir_accuracy": dir_accuracy,
        "tier_accuracy": tier_accuracy,
        "ranking_consistency": ranking_consistency,
        "dir_counts": dict(dir_counts),
        "dir_hits": dict(dir_hits),
        "confusion_matrix": confusion_matrix,
        "errors": errors,
    }


# ============================================================
#  5. 历史对比
# ============================================================

def compare_with_history(set_name: str, eval_dir: str, current_result_path: str,
                         current_accuracy: float) -> dict:
    """查找上一次同数据集的结果文件，计算准确率变化。"""
    history_files = sorted(
        [f for f in os.listdir(eval_dir)
         if f.startswith(f"eval_{set_name}_") and f != os.path.basename(current_result_path)],
        reverse=True,
    )

    if not history_files:
        return {"prev_file": None, "prev_accuracy": None, "delta": 0, "arrow": "="}

    prev_path = os.path.join(eval_dir, history_files[0])
    with open(prev_path, "r", encoding="utf-8") as f:
        prev = json.load(f)
    prev_acc = prev.get("meta", {}).get("direction_accuracy", 0)
    delta = current_accuracy - prev_acc
    arrow = "↑" if delta > 0 else "↓" if delta < 0 else "="

    return {
        "prev_file": history_files[0],
        "prev_accuracy": prev_acc,
        "delta": delta,
        "arrow": arrow,
    }


# ============================================================
#  6. 历史结果分类清理
# ============================================================

def cleanup_old_results(eval_dir: str, keep: int = 20) -> int:
    """按数据集（set_name）分类清理旧评估结果，各自独立保留最近 N 个。

    通过正则匹配文件名格式 eval_{set_name}_{timestamp}.json，
    按 set_name 分组后各自按 mtime 降序排序，每组保留最近 keep 个。

    Returns:
        删除的文件数量。
    """
    if not os.path.exists(eval_dir):
        return 0

    pattern = re.compile(r"^eval_(.+)_\d{8}_\d{6}\.json$")

    groups = {}
    for fname in os.listdir(eval_dir):
        m = pattern.match(fname)
        if not m:
            continue
        set_name = m.group(1)
        full_path = os.path.join(eval_dir, fname)
        groups.setdefault(set_name, []).append((os.path.getmtime(full_path), full_path))

    deleted = 0
    for set_name, files in groups.items():
        files.sort(key=lambda x: x[0], reverse=True)
        for _, filepath in files[keep:]:
            os.remove(filepath)
            deleted += 1

    return deleted


# ============================================================
#  7. 核心编排函数（Web 评估入口）
# ============================================================

def run_evaluation(set_name: str, profile: dict, config: dict) -> tuple:
    """执行完整评估流水线，返回 (output_data, result_path)。

    所有进度通过 emit() 推送到 SSE，meta 自动包含 model 和 estimated_cost_usd。
    """
    from job_match import execute_matching_pipeline
    from job_match import _build_profile_summary

    # ── 1. 加载数据集 ──
    cases = load_eval_dataset(set_name)
    emit(f"加载 {set_name}.json: {len(cases)} 条")

    # ── 2. 构建 jobs_list ──
    jobs_list = build_eval_jobs_list(cases)

    # ── 3. 批量调用管道（与生产环境完全一致）──
    direction_results, all_scored = execute_matching_pipeline(jobs_list, profile, config)
    total_usage = get_accumulated_usage()

    # ── 4. 生成 profile_summary ──
    profile_summary = _build_profile_summary(profile)

    # ── 5. 计算指标 ──
    metrics = compute_metrics(cases, all_scored, profile_summary,
                              direction_results=direction_results)

    # ── 6. 打印方向统计 ──
    emit(f"方向准确率: {metrics['dir_correct']}/{metrics['dir_total']} = {metrics['dir_accuracy']:.1%}")
    for d in sorted(metrics["dir_counts"]):
        emit(f"  {d}: {metrics['dir_hits'].get(d, 0)}/{metrics['dir_counts'][d]}")

    # ── 7. 打印混淆矩阵 ──
    cm = metrics["confusion_matrix"]
    emit(f"混淆矩阵 (行=expected, 列=predicted):")
    header = "           " + " ".join(f"{l:<12}" for l in cm["labels"])
    emit(header)
    for i, label in enumerate(cm["labels"]):
        row = " ".join(f"{n:<12}" for n in cm["matrix"][i])
        emit(f"  {label:<8} {row}")

    # ── 8. 自动计算模型与成本 ──
    model_name = _load_model_name()
    total_cost = _estimate_cost(model_name,
                                total_usage["input_tokens"],
                                total_usage["output_tokens"])

    # ── 9. 保存结果 ──
    eval_dir = os.path.join(OUTPUT_DIR, "eval")
    os.makedirs(eval_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = os.path.join(eval_dir, f"eval_{set_name}_{ts}.json")

    history = compare_with_history(set_name, eval_dir, result_path, metrics["dir_accuracy"])

    output_data = {
        "meta": {
            "set": set_name,
            "run_time": datetime.now().isoformat(),
            "model": model_name,
            "num_cases": len(cases),
            "errors": metrics["errors"],
            "tier_accuracy": metrics["tier_accuracy"],
            "ranking_consistency": metrics["ranking_consistency"],
            "direction_accuracy": metrics["dir_accuracy"],
            "dir_correct": metrics["dir_correct"],
            "dir_total": metrics["dir_total"],
            "total_input_tokens": total_usage["input_tokens"],
            "total_output_tokens": total_usage["output_tokens"],
            "estimated_cost_usd": total_cost,
            "confusion_matrix": cm,
            "history": {
                "prev_file": history["prev_file"],
                "prev_accuracy": history["prev_accuracy"],
                "delta": history["delta"],
                "arrow": history["arrow"],
            },
        },
        "results": metrics["results"],
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # ── 10. 历史对比日志 ──
    if history["prev_file"]:
        emit(f"历史对比 (上次: {history['prev_file']}): "
             f"{history['prev_accuracy']:.1%} → {metrics['dir_accuracy']:.1%} "
             f"({history['arrow']}{abs(history['delta']):.1%})")

    # ── 11. 清理旧结果 ──
    deleted = cleanup_old_results(eval_dir, keep=20)
    if deleted:
        emit(f"🧹 已清理 {deleted} 个旧评估文件（每组保留最近 20 个）")

    return output_data, result_path
