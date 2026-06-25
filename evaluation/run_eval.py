"""
run_eval.py — 匹配评估运行脚本

对 dev_set 或 holdout 中的每条 JD 调用 score_single_jd，计算方向准确率、
token 消耗和成本估算，输出结果 JSON 到 output/eval/。

用法:
    python evaluation/run_eval.py --dev_set          # 评估 dev_set
    python evaluation/run_eval.py --holdout          # 评估 holdout
"""
import argparse
import io
import json
import os
import sys
import time
import yaml
from datetime import datetime
from collections import Counter

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_profile, load_search_config_dict, OUTPUT_DIR
from config_assembler import load_campaign
from job_match import score_single_jd

# ── 价格常量（单位：USD / 1M tokens）──
PRICES = {
    "deepseek": {"input": 0.55, "output": 2.19},
    "deepseek-v4-pro": {"input": 0.55, "output": 2.19},
    "qwen": {"input": 0.40, "output": 1.60},
    "qwen3.6-plus": {"input": 0.40, "output": 1.60},
    "glm": {"input": 1.00, "output": 1.50},
    "glm-5.1": {"input": 1.00, "output": 1.50},
}


def _load_model_name():
    """从 search_config.yaml 读取当前模型名。"""
    try:
        cfg, _ = load_search_config_dict()
        llm_cfg = (cfg or {}).get("llm", {})
        return llm_cfg.get("model", "unknown")
    except Exception:
        return "unknown"


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算单次调用的美元成本。"""
    price = PRICES.get(model, PRICES.get("deepseek-v4-pro", {"input": 0.55, "output": 2.19}))
    return (input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"]


def is_placeholder_profile(profile: dict) -> bool:
    """
    判断用户画像是否实质有内容。
    不是检查某个具体字段是否存在，而是计算画像中有意义的信息量。
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


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dev_set", action="store_true")
    group.add_argument("--holdout", action="store_true")
    args = parser.parse_args()

    # ── 选择评估集 ──
    set_name = "dev_set" if args.dev_set else "holdout"
    input_path = os.path.join("instances", "eval", f"{set_name}.json")
    if not os.path.exists(input_path):
        print(f"ERROR: {input_path} not found. Run evaluation/split_eval.py first.")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"加载 {set_name}.json: {len(cases)} 条")

    # ── 加载用户画像 ──
    profile = load_profile()
    if is_placeholder_profile(profile):
        print("WARNING: 用户画像可能为占位模板，评分结果仅供流程验证")
    else:
        print("用户画像已加载，包含完整个人信息")

    # ── 加载配置（使用 default campaign，确保评估可复现）──
    CAMPAIGN_NAME = "default"
    print(f"Campaign: {CAMPAIGN_NAME}")
    campaign_config = load_campaign(CAMPAIGN_NAME)
    config = campaign_config
    matching_cfg = config.get("matching", {})
    weight_rules = matching_cfg.get("weight_rules", {})
    weight_profiles = matching_cfg.get("weight_profiles", {})

    model_name = _load_model_name()
    print(f"模型: {model_name}")
    print()

    # ── 逐条评分 ──
    results = []
    total_input_tokens = 0
    total_output_tokens = 0
    errors = 0

    for i, case in enumerate(cases, 1):
        jd_id = case["id"]
        jd_text = case.get("description", "")
        jd_title = case.get("title", "")
        expected_dir = case.get("expected_direction", "default")

        print(f"[{i}/{len(cases)}] {jd_id}: {jd_title[:60]} ... ", end="", flush=True)

        try:
            result = score_single_jd(
                jd_text=jd_text,
                user_profile=profile,
                config=config,
                jd_title=jd_title,
            )
        except Exception as e:
            print(f"ERROR: {e}")
            result = {
                "direction": "default",
                "scores": {},
                "total_score": 0,
                "reason": f"评分异常: {e}",
                "input_tokens": 0,
                "output_tokens": 0,
                "error": str(e),
            }
            errors += 1

        predicted_dir = result.get("direction", "default")
        match = "✓" if predicted_dir == expected_dir else f"✗ (expected {expected_dir})"
        print(f"{predicted_dir} {match}")

        total_input_tokens += result.get("input_tokens", 0)
        total_output_tokens += result.get("output_tokens", 0)

        results.append({
            "id": jd_id,
            "title": jd_title,
            "expected_direction": expected_dir,
            "predicted_direction": predicted_dir,
            "direction_correct": predicted_dir == expected_dir,
            "scores": result.get("scores", {}),
            "total_score": result.get("total_score", 0),
            "reason": result.get("reason", ""),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
        })

        # 避免限流
        time.sleep(0.5)

    # ── 方向准确率 ──
    dir_correct = sum(1 for r in results if r.get("direction_correct"))
    dir_total = len(results)
    dir_accuracy = dir_correct / dir_total if dir_total > 0 else 0
    print(f"\n方向准确率: {dir_correct}/{dir_total} = {dir_accuracy:.1%}")

    # 按方向分别统计
    print("  各方向:")
    dir_counts = Counter()
    dir_hits = Counter()
    for r in results:
        d = r["expected_direction"]
        dir_counts[d] += 1
        if r.get("direction_correct"):
            dir_hits[d] += 1
    for d in sorted(dir_counts):
        print(f"    {d}: {dir_hits[d]}/{dir_counts[d]}")

    # ── 分数档位准确率（条件执行）──
    score_ranges = [case.get("expected_score_range", "PENDING") for case in cases]
    if all(sr == "PENDING" for sr in score_ranges):
        print(f"\nscore_range 未标注（全部为 PENDING），跳过分数档位准确率计算")
    else:
        range_correct = 0
        range_total = 0
        for r, case in zip(results, cases):
            er = case.get("expected_score_range", "PENDING")
            if er == "PENDING":
                continue
            total = r.get("total_score", 0)
            if er == "high" and total >= 70:
                range_correct += 1
            elif er == "medium" and 45 <= total <= 69:
                range_correct += 1
            elif er == "low" and total < 45:
                range_correct += 1
            range_total += 1
        if range_total > 0:
            print(f"分数档位准确率: {range_correct}/{range_total} = {range_correct/range_total:.1%}")

    # ── Token 汇总 ──
    total_cost = _estimate_cost(model_name, total_input_tokens, total_output_tokens)
    print(f"\nToken 消耗:")
    print(f"  Input:  {total_input_tokens:,}")
    print(f"  Output: {total_output_tokens:,}")
    print(f"  估算成本: ${total_cost:.4f} USD")

    # ── 保存结果 ──
    eval_dir = os.path.join(OUTPUT_DIR, "eval")
    os.makedirs(eval_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = os.path.join(eval_dir, f"eval_{set_name}_{ts}.json")

    output_data = {
        "meta": {
            "set": set_name,
            "run_time": datetime.now().isoformat(),
            "model": model_name,
            "num_cases": len(cases),
            "errors": errors,
            "direction_accuracy": dir_accuracy,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "estimated_cost_usd": total_cost,
        },
        "results": results,
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {result_path}")

    # ── 历史对比 ──
    history_files = sorted(
        [f for f in os.listdir(eval_dir) if f.startswith(f"eval_{set_name}_") and f != os.path.basename(result_path)],
        reverse=True,
    )
    if history_files:
        prev_path = os.path.join(eval_dir, history_files[0])
        with open(prev_path, "r", encoding="utf-8") as f:
            prev = json.load(f)
        prev_meta = prev.get("meta", {})
        prev_acc = prev_meta.get("direction_accuracy", 0)
        prev_cost = prev_meta.get("estimated_cost_usd", 0)
        delta_acc = dir_accuracy - prev_acc
        delta_cost = total_cost - prev_cost
        print(f"\n历史对比 (上次: {history_files[0]}):")
        print(f"  方向准确率: {prev_acc:.1%} → {dir_accuracy:.1%} "
              f"({'↑' if delta_acc > 0 else '↓' if delta_acc < 0 else '='}{abs(delta_acc):.1%})")
        print(f"  成本: ${prev_cost:.4f} → ${total_cost:.4f} "
              f"({'↑' if delta_cost > 0 else '↓' if delta_cost < 0 else '='}${abs(delta_cost):.4f})")
    else:
        print("\n无历史结果可对比")


if __name__ == "__main__":
    main()
