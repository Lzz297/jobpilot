"""
run_checker_eval.py — 核查评估运行脚本

加载 mock_me.yaml 和 checker_test_cases.json，逐条调用 check_bullet() 比对结果。
当前 check_bullet 尚未实现，脚本以优雅跳过模式运行（退出码 0）。

用法:
    python evaluation/run_checker_eval.py
"""
import io
import json
import os
import sys
import yaml
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    # ── 加载 mock_me.yaml ──
    mock_path = os.path.join("instances", "eval", "mock_me.yaml")
    if not os.path.exists(mock_path):
        print(f"ERROR: {mock_path} not found.")
        sys.exit(1)

    with open(mock_path, "r", encoding="utf-8") as f:
        mock_me = yaml.safe_load(f)

    experiences = mock_me.get("experiences", [])
    id_to_text = {exp["id"]: exp["text"] for exp in experiences}
    print(f"加载 mock_me.yaml: {len(experiences)} 条 experience 条目")

    # ── 加载 checker_test_cases.json ──
    cases_path = os.path.join("instances", "eval", "checker_test_cases.json")
    if not os.path.exists(cases_path):
        print(f"ERROR: {cases_path} not found.")
        sys.exit(1)

    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"加载 checker_test_cases.json: {len(cases)} 条测试用例")

    # ── 尝试导入 check_bullet ──
    try:
        # check_bullet 将在战役三中实现，预计路径未知，尝试常见位置
        from resume_gen import check_bullet  # type: ignore
        CHECKER_AVAILABLE = True
    except ImportError:
        try:
            from checker import check_bullet  # type: ignore
            CHECKER_AVAILABLE = True
        except ImportError:
            CHECKER_AVAILABLE = False

    if not CHECKER_AVAILABLE:
        print()
        print("=" * 60)
        print("  check_bullet 尚未实现 — 优雅跳过")
        print("=" * 60)
        print()
        print(f"  已加载 {len(cases)} 条测试用例，待战役三实现 check_bullet 后可运行。")
        print(f"  mock_me.yaml: {len(experiences)} 条条目就绪。")
        print()
        print(f"  预期测试覆盖:")
        for c in cases:
            flags_str = ", ".join(c["expected_flags"]) if c["expected_flags"] else "(clean)"
            print(f"    {c['id']}: expected_flags=[{flags_str}]")
        print()
        print("  退出码 0（非错误）")
        sys.exit(0)

    # ── 以下仅在 check_bullet 可用时执行 ──
    print(f"\ncheck_bullet 已就绪，开始逐条评估...\n")

    passed = 0
    failed = 0
    details = []

    for case in cases:
        cid = case["id"]
        source_ids = case["source_ids"]
        resume_bullet = case["resume_bullet"]
        expected = set(case.get("expected_flags", []))

        try:
            actual = set(check_bullet(source_ids, mock_me, resume_bullet))
        except Exception as e:
            actual = {f"ERROR: {e}"}

        ok = actual == expected
        if ok:
            passed += 1
            print(f"  ✓ {cid}")
        else:
            failed += 1
            print(f"  ✗ {cid}: expected={sorted(expected)}, actual={sorted(actual)}")

        details.append({
            "id": cid,
            "passed": ok,
            "expected_flags": sorted(expected),
            "actual_flags": sorted(actual),
            "resume_bullet": resume_bullet,
            "source_ids": source_ids,
        })

    # ── 汇总 ──
    print(f"\n核查评估结果: {passed}/{len(cases)} 通过")
    if failed > 0:
        print(f"  失败: {failed} 条")
        for d in details:
            if not d["passed"]:
                print(f"    {d['id']}: expected={d['expected_flags']} actual={d['actual_flags']}")

    # ── 保存结果 ──
    from config import OUTPUT_DIR
    eval_dir = os.path.join(OUTPUT_DIR, "eval")
    os.makedirs(eval_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = os.path.join(eval_dir, f"checker_eval_{ts}.json")

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "run_time": datetime.now().isoformat(),
                "checker_available": CHECKER_AVAILABLE,
                "total_cases": len(cases),
                "passed": passed,
                "failed": failed,
            },
            "details": details,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存: {result_path}")


if __name__ == "__main__":
    main()
