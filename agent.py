"""
agent.py - JobsDB 智能求职 Agent 主入口（终端模式）
"""
import argparse
import sys
from config import llm_call, print_session_summary, get_system_prompt
from tools_defs import tools, tool_map, execute_tool, deduplicate_tool_calls
from scraper import cleanup_playwright
from pdf_renderer import cleanup_renderer


# ============================================================
#  Agent 主循环
# ============================================================

def run_agent_loop():
    """终端对话交互循环"""
    messages = [{"role": "system", "content": get_system_prompt()}]

    print("=" * 50)
    print("[Agent] JobsDB 智能求职 Agent 已启动！")
    print("=" * 50)
    print()
    print("你可以说：")
    print("  [Job] 「帮我找工作」              → 三层漏斗搜索 + 匹配分析")
    print("  [List] 「看看匹配结果」            → 查看多维度排名列表")
    print("  [Market] 「分析 Java 开发市场行情」    → 独立市场调研（技能/薪资/差距）")
    print("  [Resume] 「为第1个生成简历」          → 基于匹配岗位生成定制简历")
    print("  [Resume]  直接粘贴 JD + 「生成简历」  → 基于任意 JD 生成")
    print("  [Profile] 「看看我的档案」            → 查看个人配置")
    print("  [Search] 「搜索 xxx」               → 自由搜索")
    print("  [File] 「查看这个岗位 URL」         → 抓取单个岗位完整JD")
    print("  输入 quit 退出")
    print()

    while True:
        user_input = input("你: ").strip()
        if user_input.lower() == "quit":
            print("[Bye] 再见，祝你求职顺利！")
            cleanup_playwright()
            cleanup_renderer()
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        reply = llm_call(messages, tools=tools)
        messages.append(reply)

        # 工具调用循环
        while reply.tool_calls:
            print("[Tool] Agent 正在工作...")

            unique_calls = deduplicate_tool_calls(reply.tool_calls)

            for tc in unique_calls:
                result = execute_tool(tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                })

            skipped = [tc for tc in reply.tool_calls if tc not in unique_calls]
            for tc in skipped:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "（重复调用已跳过）"
                })

            reply = llm_call(messages, tools=tools)
            messages.append(reply)

        print(f"\n[Agent]: {reply.content}\n")

        # ── 本轮结束，打印文件总览 ──
        print_session_summary()


# ============================================================
#  入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobsDB 智能求职 Agent")
    parser.add_argument("--campaign", type=str, default=None,
                        help="Campaign 名称（如 web3_hunt），使用 instances/campaigns/ 下的配置")
    args = parser.parse_args()

    if not args.campaign:
        print("[ERROR] 必须指定 --campaign 参数。")
        print("可用 campaign 请查看 instances/campaigns/ 目录。")
        import os as _os
        d = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "instances", "campaigns")
        if _os.path.isdir(d):
            for f in sorted(_os.listdir(d)):
                if f.endswith(".yaml"):
                    print(f"  - {f.replace('.yaml', '')}")
        print("示例: python agent.py --campaign web3_hunt")
        sys.exit(1)

    from config_assembler import load_campaign
    from config import set_campaign_config
    try:
        campaign_config = load_campaign(args.campaign)
        set_campaign_config(campaign_config)
        print(f"[OK] Campaign loaded: {args.campaign}")
        print(f"    User: {campaign_config.get('user_profile', {}).get('name', 'N/A')}")
        print(f"    Strategy: {campaign_config['strategy_name']}")
        print(f"    Search queries: {len(campaign_config.get('search_queries', []))} groups")
    except Exception as e:
        print(f"[ERROR] Campaign load failed: {e}")
        sys.exit(1)

    run_agent_loop()
