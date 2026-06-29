"""
run_eval.py — 匹配评估 CLI 入口

用法:
    python evaluation/run_eval.py --dev_set          # 评估 dev_set
    python evaluation/run_eval.py --holdout          # 评估 holdout
"""
import argparse
import io
import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_profile, load_search_config_dict
from config_assembler import load_campaign
from eval_core import run_evaluation


# ── 价格常量（单位：USD / 1M tokens）──
PRICES = {
    "deepseek": {"input": 0.55, "output": 2.19},
    "deepseek-v4-pro": {"input": 0.55, "output": 2.19},
    "qwen": {"input": 0.40, "output": 1.60},
    "qwen3.6-plus": {"input": 0.40, "output": 1.60},
    "glm": {"input": 1.00, "output": 1.50},
    "glm-5.1": {"input": 1.00, "output": 1.50},
}


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
    """判断用户画像是否实质有内容。"""
    if not profile:
        return True
    score = 0
    work = profile.get("work_experience", [])
    if work and len(work) > 0:
        first = work[0]
        if first.get("description") or first.get("highlights") or first.get("core_modules"):
            score += 3
        elif first.get("company") and first.get("title"):
            score += 1
    skills = profile.get("skills", {})
    skill_count = sum(len(items) for items in skills.values() if isinstance(items, list))
    if skill_count >= 5:
        score += 3
    elif skill_count >= 2:
        score += 2
    elif skill_count >= 1:
        score += 1
    projects = profile.get("projects", [])
    if projects and any(p.get("description") or p.get("resume_bullets") for p in projects):
        score += 2
    summary = profile.get("summary", "")
    if summary and len(summary.strip()) > 50:
        score += 1
    return score < 3


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dev_set", action="store_true")
    group.add_argument("--holdout", action="store_true")
    args = parser.parse_args()

    set_name = "dev_set" if args.dev_set else "holdout"
    input_path = os.path.join("instances", "eval", f"{set_name}.json")
    if not os.path.exists(input_path):
        print(f"ERROR: {input_path} not found. Run evaluation/split_eval.py first.")
        sys.exit(1)

    # ── 加载用户画像 ──
    profile = load_profile()
    if is_placeholder_profile(profile):
        print("WARNING: 用户画像可能为占位模板，评分结果仅供流程验证")
    else:
        print("用户画像已加载，包含完整个人信息")

    # ── 加载 Campaign 配置 ──
    CAMPAIGN_NAME = "default"
    print(f"Campaign: {CAMPAIGN_NAME}")
    config = load_campaign(CAMPAIGN_NAME)

    model_name = _load_model_name()
    print(f"模型: {model_name}")
    print()

    # ── 调用核心评估流水线 ──
    output_data, result_path = run_evaluation(
        set_name, profile, config,
        progress_callback=print,
    )

    meta = output_data["meta"]
    print(f"\nToken 消耗:")
    print(f"  Input:  {meta['total_input_tokens']:,}")
    print(f"  Output: {meta['total_output_tokens']:,}")
    total_cost = _estimate_cost(model_name,
                                meta["total_input_tokens"],
                                meta["total_output_tokens"])
    print(f"  估算成本: ${total_cost:.4f} USD")

    print(f"\n结果已保存: {result_path}")


if __name__ == "__main__":
    main()
