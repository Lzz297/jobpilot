"""
eval_core.py — 评估公共核心模块

CLI (run_eval.py) 和 Web (_run_eval_sse) 共享的评估逻辑。
提供 load_eval_dataset / build_eval_jobs_list / compute_metrics /
compare_with_history / cleanup_old_results / run_evaluation 六个函数。
"""
import json
import os
import re
from datetime import datetime
from collections import Counter


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
            "labels": ["default", "payment", "solutions", "technical", "web3"],
            "matrix": [[8, 0, 1, 2, 0], ...]  # matrix[i][j] = expected=labels[i] 被预测为 labels[j] 的数量
        }
    """
    # 收集所有出现过的方向标签
    all_dirs = set()
    for r in results:
        all_dirs.add(r["expected_direction"])
        all_dirs.add(r["predicted_direction"])
    labels = sorted(all_dirs)  # 字母序保证稳定

    # 构建 label -> index 映射
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

def compute_metrics(cases: list, all_scored: list, profile_summary: str) -> dict:
    """将 all_scored 按 eval_id 匹配到 cases，计算结果列表和各项指标。

    Args:
        cases: 原始标注数据列表
        all_scored: execute_matching_pipeline 返回的评分结果列表
        profile_summary: 用户画像摘要 JSON 字符串（注入每条 result）

    Returns:
        {
            "results": [...],
            "dir_correct": 15,
            "dir_total": 20,
            "dir_accuracy": 0.75,
            "dir_counts": {"technical": 10, "web3": 5, ...},
            "dir_hits": {"technical": 8, "web3": 4, ...},
            "confusion_matrix": {...},
            "errors": 0,
        }
    """
    scored_dict = {s["eval_id"]: s for s in all_scored if s.get("eval_id")}
    results = []
    errors = 0

    for case in cases:
        scored = scored_dict.get(case["id"])
        if scored:
            predicted_dir = scored.get("llm_direction", "default")
            scores = scored.get("scores", {})
            total_score = scored.get("total_score", 0)
            reason = scored.get("reason", "")
        else:
            predicted_dir = "default"
            scores = {}
            total_score = 0
            reason = "未在匹配结果中找到该岗位"
            errors += 1

        expected_dir = case.get("expected_direction", "default")

        results.append({
            "id": case["id"],
            "title": case["title"],
            "expected_direction": expected_dir,
            "predicted_direction": predicted_dir,
            "direction_correct": predicted_dir == expected_dir,
            "scores": scores,
            "total_score": total_score,
            "reason": reason,
            "input_tokens": 0,
            "output_tokens": 0,
            # ── 离线分析支撑字段 ──
            "description": case["description"],
            "profile_summary": profile_summary,
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

    return {
        "results": results,
        "dir_correct": dir_correct,
        "dir_total": dir_total,
        "dir_accuracy": dir_accuracy,
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
    """查找上一次同数据集的结果文件，计算准确率变化。

    Returns:
        {
            "prev_file": "eval_dev_set_20260628_120000.json" or None,
            "prev_accuracy": 0.72 or None,
            "delta": 0.03,
            "arrow": "↑" or "↓" or "=",
        }
    """
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

    # 匹配文件名格式: eval_{set_name}_YYYYMMDD_HHMMSS.json
    pattern = re.compile(r"^eval_(.+)_\d{8}_\d{6}\.json$")

    # 按 set_name 分组
    groups = {}  # set_name -> [(mtime, filepath), ...]
    for fname in os.listdir(eval_dir):
        m = pattern.match(fname)
        if not m:
            continue
        set_name = m.group(1)
        full_path = os.path.join(eval_dir, fname)
        groups.setdefault(set_name, []).append((os.path.getmtime(full_path), full_path))

    # 每个 set 独立排序并删除多余文件
    deleted = 0
    for set_name, files in groups.items():
        files.sort(key=lambda x: x[0], reverse=True)  # mtime 降序
        for _, filepath in files[keep:]:
            os.remove(filepath)
            deleted += 1

    return deleted


# ============================================================
#  7. 核心编排函数（CLI 和 Web 共用入口）
# ============================================================

def run_evaluation(set_name: str, profile: dict, config: dict,
                   progress_callback=None) -> tuple:
    """执行完整评估流水线，返回 (output_data, result_path)。

    Args:
        set_name: 数据集名称 ("dev_set" 或 "holdout")
        profile: 用户画像字典
        config:  Campaign 配置字典
        progress_callback: 可选的进度回调函数，签名为 callback(msg: str)

    Returns:
        (output_data, result_path)
        output_data 的格式：
        {
            "meta": { "set", "run_time", "num_cases", "errors",
                      "direction_accuracy", "dir_correct", "dir_total",
                      "total_input_tokens", "total_output_tokens",
                      "confusion_matrix", "history" },
            "results": [ ... ]
        }
    """
    from config import clear_usage_accumulator, get_accumulated_usage, OUTPUT_DIR
    from job_match import execute_matching_pipeline
    from job_match import _build_profile_summary

    def emit(msg: str):
        if progress_callback:
            progress_callback(msg)

    # ── 1. 加载数据集 ──
    cases = load_eval_dataset(set_name)
    emit(f"加载 {set_name}.json: {len(cases)} 条")

    # ── 2. 构建 jobs_list ──
    jobs_list = build_eval_jobs_list(cases)

    # ── 3. 批量调用管道（与生产环境完全一致）──
    clear_usage_accumulator()
    all_scored = execute_matching_pipeline(jobs_list, profile, config)
    total_usage = get_accumulated_usage()

    # ── 4. 生成 profile_summary ──
    profile_summary = _build_profile_summary(profile)

    # ── 5. 计算指标 ──
    metrics = compute_metrics(cases, all_scored, profile_summary)

    # ── 6. 打印结果 ──
    emit(f"方向准确率: {metrics['dir_correct']}/{metrics['dir_total']} = {metrics['dir_accuracy']:.1%}")
    for d in sorted(metrics["dir_counts"]):
        emit(f"  {d}: {metrics['dir_hits'].get(d, 0)}/{metrics['dir_counts'][d]}")

    # 混淆矩阵日志
    cm = metrics["confusion_matrix"]
    emit(f"混淆矩阵 (行=expected, 列=predicted):")
    header = "           " + " ".join(f"{l:<12}" for l in cm["labels"])
    emit(header)
    for i, label in enumerate(cm["labels"]):
        row = " ".join(f"{n:<12}" for n in cm["matrix"][i])
        emit(f"  {label:<8} {row}")

    # ── 7. 保存结果 ──
    eval_dir = os.path.join(OUTPUT_DIR, "eval")
    os.makedirs(eval_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = os.path.join(eval_dir, f"eval_{set_name}_{ts}.json")

    history = compare_with_history(set_name, eval_dir, result_path, metrics["dir_accuracy"])

    output_data = {
        "meta": {
            "set": set_name,
            "run_time": datetime.now().isoformat(),
            "num_cases": len(cases),
            "errors": metrics["errors"],
            "direction_accuracy": metrics["dir_accuracy"],
            "dir_correct": metrics["dir_correct"],
            "dir_total": metrics["dir_total"],
            "total_input_tokens": total_usage["input_tokens"],
            "total_output_tokens": total_usage["output_tokens"],
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

    # ── 8. 历史对比日志 ──
    if history["prev_file"]:
        emit(f"历史对比 (上次: {history['prev_file']}): "
             f"{history['prev_accuracy']:.1%} → {metrics['dir_accuracy']:.1%} "
             f"({history['arrow']}{abs(history['delta']):.1%})")

    # ── 9. 清理旧结果 ──
    deleted = cleanup_old_results(eval_dir, keep=20)
    if deleted:
        emit(f"🧹 已清理 {deleted} 个旧评估文件（每组保留最近 20 个）")

    return output_data, result_path
