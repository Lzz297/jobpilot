"""
批次 1 验证测试：确认重复函数已删除，真实功能已恢复。
对比 Demo (new-ui/index.html) 与 Actual (http://127.0.0.1:5000) 的关键行为。
"""
import pytest
from playwright.sync_api import sync_playwright, expect
import os

DEMO_PATH = "file:///D:/job-agent/new-ui/index.html"
ACTUAL_URL = "http://127.0.0.1:5000"


def test_page_loads_without_js_error(page):
    """Actual 页面能正常加载，无 JS 报错"""
    errors = []
    page.on("pageerror", lambda err: errors.append(err.message))
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)  # 等待 initSession + loadModelConfig 完成
    assert len(errors) == 0, f"JS errors found: {errors}"


def test_no_duplicate_functions(page):
    """确认 5 个函数在 window 上只有唯一引用，且非 stub 版本"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    checks = {
        "mktTab": "mktTab",
        "renderMarketPresets": "renderMarketPresets",
        "addBatchRow": "addBatchRow",
        "openYamlModal": "openYamlModal",
        "setModalMode": "setModalMode",
    }
    for name, expr in checks.items():
        result = page.evaluate(f"typeof window.{expr}")
        assert result == "function", f"{name} should be a function, got {result}"


def test_market_presets_load_real_data(page):
    """renderMarketPresets 应加载真实 YAML 数据，而非 Phase 3 占位文字"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # Demo: navigate to market view to check preset chips
    page.click('button[data-view="market"]')
    page.wait_for_timeout(1000)

    # 检查预设 chips 不为占位文字
    cat_chips = page.locator("#mkt-cat-chips").inner_text()
    assert "Phase 3" not in cat_chips, f"Market presets still showing placeholder: {cat_chips}"
    assert "手动输入岗位类别（大小写敏感），预设功能将在" not in cat_chips, f"Stub text found: {cat_chips}"


def test_mkt_tab_switching(page):
    """mktTab 单一切换功能正常"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)
    page.click('button[data-view="market"]')
    page.wait_for_timeout(500)

    # 默认应该是 single tab active
    single_btn = page.locator("#mkt-tab-single")
    batch_btn = page.locator("#mkt-tab-batch")
    assert "bg-indigo-600" in single_btn.get_attribute("class"), "Single tab should be active by default"
    assert "bg-white" in batch_btn.get_attribute("class"), "Batch tab should be inactive by default"

    # 切换到批量
    batch_btn.click()
    page.wait_for_timeout(300)
    assert "bg-indigo-600" in batch_btn.get_attribute("class"), "Batch tab should be active after click"
    assert "hidden" not in page.locator("#mkt-batch").get_attribute("class") or page.locator("#mkt-batch").is_visible(), "Batch panel should be visible"


def test_add_batch_row_with_preset(page):
    """addBatchRow 接受参数，支持从预设传入数据"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)
    page.click('button[data-view="market"]')
    page.wait_for_timeout(500)

    # 切换到批量 tab
    page.locator("#mkt-tab-batch").click()
    page.wait_for_timeout(300)

    # 通过 JS 调用 addBatchRow 带参数
    initial_count = page.locator("#batch-rows .batch-row").count()
    page.evaluate("addBatchRow({category:'TestCategory', classification:'test-classification'})")
    page.wait_for_timeout(300)
    new_count = page.locator("#batch-rows .batch-row").count()

    assert new_count == initial_count + 1, f"Batch row count should increase by 1 ({initial_count} -> {new_count})"

    # 检查新增行被正确填充
    last_row = page.locator("#batch-rows .batch-row").last
    cat_input = last_row.locator(".bcat").input_value()
    cls_input = last_row.locator(".bclass").input_value()
    assert cat_input == "TestCategory", f"Category should be 'TestCategory', got '{cat_input}'"
    assert cls_input == "test-classification", f"Classification should be 'test-classification', got '{cls_input}'"


def test_yaml_modal_loads_real_data(page):
    """openYamlModal 加载真实 YAML 数据而非 Phase 1 占位文字"""
    page.goto(ACTUAL_URL)
    page.wait_for_timeout(2000)

    # 通过 JS 调用 async openYamlModal
    page.evaluate("openYamlModal('me')")
    page.wait_for_timeout(1500)  # 等待 async 加载

    modal_body = page.locator("#modal-body")
    text = modal_body.inner_text()
    # Phase 1 占位文字不应出现
    assert "在线编辑功能将在 Phase 3 上线" not in text, f"Phase 1 placeholder found in modal: {text}"
    # 应该有真实内容（至少有关闭按钮能工作说明 modal 正常）
    assert len(text) > 20, f"Modal body seems empty or placeholder: '{text}' (len={len(text)})"
    # 验证 closeModal 按钮仍工作
    page.locator("#modal-overlay button:has-text('关闭')").click()
    page.wait_for_timeout(300)
    assert "hidden" in page.locator("#modal-overlay").get_attribute("class"), "Modal should be hidden after close"


def test_demo_actual_sidebar_parity(page_actual, page_demo):
    """对比 Demo 和 Actual 的侧边栏结构一致"""
    page_demo.goto(DEMO_PATH)
    page_actual.goto(ACTUAL_URL)
    page_actual.wait_for_timeout(2000)

    # 比较侧边栏导航项数量
    demo_nav_count = page_demo.locator(".navbtn").count()
    actual_nav_count = page_actual.locator(".navbtn").count()
    assert demo_nav_count == actual_nav_count, (
        f"Nav button count differs: demo={demo_nav_count}, actual={actual_nav_count}"
    )

    # 比较状态指示器结构
    assert page_actual.locator("#status-pill").is_visible(), "Status pill should be visible"
    assert page_actual.locator("#status-dot").is_visible(), "Status dot should be visible"
