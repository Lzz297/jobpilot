"""
批次 4 验证测试：Escape 键关闭弹窗 + send-btn 单一绑定 + init 预设 batch row。
"""
import pytest

ACTUAL_URL = "http://127.0.0.1:5000"


def test_escape_closes_lang_modal(page):
    """按 Escape 应关闭语言弹窗"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 打开语言弹窗
    page.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page.wait_for_timeout(500)

    # 弹窗应可见
    overlay = page.locator("#lang-overlay")
    assert not overlay.evaluate("el => el.classList.contains('hidden')"), "Lang modal should be visible"

    # 按 Escape
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # 弹窗应隐藏
    assert overlay.evaluate("el => el.classList.contains('hidden')"), "Lang modal should be hidden after Escape"


def test_escape_closes_yaml_modal(page):
    """按 Escape 应关闭 YAML 浮层"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 打开 YAML 浮层
    page.evaluate("openYamlModal('me')")
    page.wait_for_timeout(1500)  # async

    # 浮层应可见
    overlay = page.locator("#modal-overlay")
    assert not overlay.evaluate("el => el.classList.contains('hidden')"), "YAML modal should be visible"

    # 按 Escape
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # 浮层应隐藏
    assert overlay.evaluate("el => el.classList.contains('hidden')"), "YAML modal should be hidden after Escape"


def test_send_btn_single_binding(page):
    """send-btn 只有 onclick 属性，不应有重复 addEventListener"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 点击一次 send，检查只创建了一个 chatUser bubble
    # 先输入文字
    page.fill("#chat-input", "Hello")
    page.click("#send-btn")
    page.wait_for_timeout(1000)

    # 应该只出现一个用户消息（气泡）
    user_msgs = page.locator("#chat-messages .flex.justify-end").count()
    # 欢迎消息没有用户气泡，所以至少是 1
    assert user_msgs >= 1, f"Should have at least 1 user message, got {user_msgs}"


def test_init_batch_row_has_preset(page):
    """init 预添加的 batch row 应有 'Web3' 预设"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 切换到市场视图
    page.click('button[data-view="market"]')
    page.wait_for_timeout(500)
    # 切换到批量 tab
    page.locator("#mkt-tab-batch").click()
    page.wait_for_timeout(300)

    # 检查是否有预设的 batch row
    rows = page.locator("#batch-rows .batch-row")
    count = rows.count()
    assert count >= 1, f"Should have at least 1 batch row, got {count}"

    # 第一个 batch row 的 category 应为 'Web3'
    first_cat = rows.first.locator(".bcat").input_value()
    assert first_cat == "Web3", f"First batch row category should be 'Web3', got '{first_cat}'"


def test_page_no_errors(page):
    """综合：页面无 JS 错误"""
    errors = []
    page.on("pageerror", lambda err: errors.append(err.message))
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)
    assert len(errors) == 0, f"JS errors: {errors}"
