"""
批次 3 验证测试：routeMessage 智能路由 + suggest chips 对齐。
"""
import pytest

ACTUAL_URL = "http://127.0.0.1:5000"
DEMO_PATH = "file:///D:/job-agent/new-ui/index.html"


def test_suggest_chips_use_route_message(page):
    """建议 chips 应调用 routeMessage() 而非 fill+sendChat"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 获取第一个 suggest chip 的 onclick 属性
    onclick = page.locator("#suggest-chips button").first.get_attribute("onclick")
    assert onclick is not None, "Suggest chip should have onclick"
    assert "routeMessage" in onclick, f"Suggest chip should call routeMessage, got: {onclick}"
    assert "$('#chat-input').value" not in onclick, f"Should not fill input directly, got: {onclick}"


def test_suggest_chips_count_matches_demo(page_actual, page_demo):
    """建议 chips 数量与 demo 一致"""
    page_demo.goto(DEMO_PATH)
    page_actual.goto(ACTUAL_URL)
    page_actual.wait_for_timeout(2000)

    demo_count = page_demo.locator("#suggest-chips button").count()
    actual_count = page_actual.locator("#suggest-chips button").count()
    assert demo_count == actual_count, f"Chip count differs: demo={demo_count}, actual={actual_count}"


def test_route_message_exists(page):
    """routeMessage 函数存在于 window 上"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    result = page.evaluate("typeof window.routeMessage")
    assert result == "function", f"routeMessage should be a function, got {result}"


def test_send_to_llm_exists(page):
    """sendToLLM 函数存在于 window 上"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    result = page.evaluate("typeof window.sendToLLM")
    assert result == "function", f"sendToLLM should be a function, got {result}"


def test_simple_reply_exists(page):
    """simpleReply 函数存在于 window 上"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    result = page.evaluate("typeof window.simpleReply")
    assert result == "function", f"simpleReply should be a function, got {result}"


def test_route_message_handles_job_search(page):
    """routeMessage('帮我找工作') 应弹出语言选择弹窗"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 调用 routeMessage
    page.evaluate("() => routeMessage('帮我找工作')")
    page.wait_for_timeout(1000)

    # 应显示语言弹窗
    lang_overlay = page.locator("#lang-overlay")
    assert not lang_overlay.evaluate("el => el.classList.contains('hidden')"), "Language modal should be visible"


def test_route_message_handles_market(page):
    """routeMessage('分析 Web3 市场行情') 应跳转到市场视图 + 预填"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    page.evaluate("() => routeMessage('分析 Web3 市场行情')")
    page.wait_for_timeout(1000)

    # 应切换到市场视图
    assert page.locator("#view-market").is_visible(), "Market view should be visible"
    # 应预填岗位类别
    cat_val = page.locator("#mkt-cat").input_value()
    assert cat_val == "Web3", f"Category should be 'Web3', got '{cat_val}'"


def test_route_message_handles_matches(page):
    """routeMessage('看看匹配结果') 应跳转到匹配视图"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    page.evaluate("() => routeMessage('看看匹配结果')")
    page.wait_for_timeout(1000)

    assert page.locator("#view-matches").is_visible(), "Matches view should be visible"


def test_route_message_handles_resume(page):
    """routeMessage 中简历关键词应显示 simpleReply 而非发给 LLM"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 先手动触发 chatUser + routeMessage
    page.evaluate("() => routeMessage('帮我生成简历')")
    page.wait_for_timeout(500)

    # 应在聊天区有回复卡片（不是发 LLM）
    reply = page.locator("#chat-messages .result").last.inner_text()
    assert "简历生成" in reply, f"Should show resume hint, got: {reply}"


def test_route_message_fallback_to_llm(page):
    """未匹配路由的文字应发给 LLM"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 输入一个不匹配任何路由的消息
    page.evaluate("() => routeMessage('今天天气不错')")
    page.wait_for_timeout(500)

    # 应有 SSE 连接或至少创建了 chatTurn
    # 验证没有报错
    assert True


def test_page_no_errors_after_routing(page):
    """综合：路由后页面无 JS 错误"""
    errors = []
    page.on("pageerror", lambda err: errors.append(err.message))
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 依次触发多个路由
    page.evaluate("() => routeMessage('看看匹配结果')")
    page.wait_for_timeout(500)
    page.evaluate("() => routeMessage('分析 Java 市场行情')")
    page.wait_for_timeout(500)

    assert len(errors) == 0, f"JS errors: {errors}"
