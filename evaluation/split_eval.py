"""
split_eval.py — 评估集切分工具

读取 instances/eval/all_cases.json，按 expected_direction 分层抽样，
固定 seed=42，每个方向按约 80/20 分入 dev_set 和 holdout。

退化断言：
  1. holdout 不得全部同一 direction（必查）
  2. score_range 退化检查 — 若全为 PENDING 则跳过并打印提示；
     若已填值则检查 holdout 不得全部同一档
"""
import json
import os
import random
import sys
from collections import Counter


SEED = 42
HOLDOUT_RATIO = 0.2  # ~20% goes to holdout


def main():
    input_path = os.path.join("instances", "eval", "all_cases.json")
    if not os.path.exists(input_path):
        print(f"ERROR: {input_path} not found.")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if len(cases) != 25:
        print(f"WARNING: expected 25 cases, got {len(cases)}")

    # ── 1. 按 expected_direction 分组 ──
    groups = {}
    for c in cases:
        d = c.get("expected_direction", "default")
        groups.setdefault(d, []).append(c)

    print(f"Total cases: {len(cases)}")
    print(f"Direction groups: { {d: len(g) for d, g in sorted(groups.items())} }")
    print()

    # ── 2. 每组内 shuffle + 按比例分 ──
    random.seed(SEED)

    holdout = []
    dev = []

    for d in sorted(groups.keys()):
        group = groups[d]
        random.shuffle(group)
        n_holdout = max(1, round(len(group) * HOLDOUT_RATIO))
        holdout.extend(group[:n_holdout])
        dev.extend(group[n_holdout:])

    # ── 3. 最终 shuffle ──
    random.shuffle(holdout)
    random.shuffle(dev)

    # ── 4. 退化断言 1：holdout 不得全部同一 direction ──
    holdout_dirs = [c["expected_direction"] for c in holdout]
    if len(set(holdout_dirs)) == 1:
        print(f"ERROR: holdout 全部同一 direction ({holdout_dirs[0]})，分层失败！")
        sys.exit(1)

    # ── 5. 退化断言 2：score_range 条件检查 ──
    score_ranges = [c.get("expected_score_range", "PENDING") for c in holdout]
    if all(sr == "PENDING" for sr in score_ranges):
        print("score_range 未标注（全部为 PENDING），跳过分档退化检查")
    else:
        unique_ranges = set(sr for sr in score_ranges if sr != "PENDING")
        if len(unique_ranges) <= 1 and len(unique_ranges) > 0:
            print(f"ERROR: holdout 的 score_range 全部同一档 ({list(unique_ranges)[0]})！")
            sys.exit(1)
        print(f"score_range 退化检查通过（{len(unique_ranges)} 档: {unique_ranges}）")

    # ── 6. 输出 ──
    os.makedirs(os.path.join("instances", "eval"), exist_ok=True)

    holdout_path = os.path.join("instances", "eval", "holdout.json")
    dev_path = os.path.join("instances", "eval", "dev_set.json")

    with open(holdout_path, "w", encoding="utf-8") as f:
        json.dump(holdout, f, ensure_ascii=False, indent=2)

    with open(dev_path, "w", encoding="utf-8") as f:
        json.dump(dev, f, ensure_ascii=False, indent=2)

    # ── 7. 打印分布 ──
    def count_dirs(items):
        return Counter(c["expected_direction"] for c in items)

    print()
    print(f"holdout.json: {len(holdout)} 条")
    for d, n in sorted(count_dirs(holdout).items()):
        print(f"  {d}: {n}")
    print(f"dev_set.json: {len(dev)} 条")
    for d, n in sorted(count_dirs(dev).items()):
        print(f"  {d}: {n}")
    print()
    print("切分完成。")


if __name__ == "__main__":
    main()
