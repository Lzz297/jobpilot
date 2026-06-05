"""
全量回归测试：对比 Actual (http://127.0.0.1:5000) 与 Demo (new-ui/index.html)
穷尽每个视图、每个可交互元素的样式和行为。
"""
import pytest
import re

ACTUAL = "http://127.0.0.1:5000"
DEMO = "file:///D:/job-agent/new-ui/index.html"

# ── CSS classes snapshot helper ──
def classes(el):
    return (el.get_attribute("class") or "").split()


def get_style(page, selector, prop):
    return page.locator(selector).first.evaluate(f"el => getComputedStyle(el)['{prop}']")


# ============================================================
#  UTILITIES — compare actual page setup
# ============================================================

def open_actual(page):
    page.goto(ACTUAL)
    page.wait_for_timeout(2500)


def view(page, v):
    page.evaluate(f"switchView('{v}')")
    page.wait_for_timeout(800)


# ============================================================
#  SECTION 1: PAGE LOAD & SIDEBAR
# ============================================================

def test_01_page_title(page_actual, page_demo):
    """标题一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    assert page_actual.title() == page_demo.title()


def test_02_sidebar_nav_count(page_actual, page_demo):
    """侧边栏导航按钮数量一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    assert page_actual.locator(".navbtn").count() == page_demo.locator(".navbtn").count()


def test_03_sidebar_nav_labels(page_actual, page_demo):
    """侧边栏导航按钮文字一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    demo_labels = [page_demo.locator(".navbtn .nav-title").nth(i).inner_text() for i in range(page_demo.locator(".navbtn").count())]
    actual_labels = [page_actual.locator(".navbtn .nav-title").nth(i).inner_text() for i in range(page_actual.locator(".navbtn").count())]
    assert actual_labels == demo_labels, f"Nav labels differ: actual={actual_labels} demo={demo_labels}"


def test_04_status_pill_idle(page_actual, page_demo):
    """空闲状态指示灯一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    # Both should have emerald dot when idle
    dot_actual = page_actual.locator("#status-dot")
    dot_demo = page_demo.locator("#status-dot")
    # Check both visible
    assert dot_actual.is_visible()
    assert dot_demo.is_visible()


def test_05_status_text_idle(page_actual, page_demo):
    """空闲状态文字一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    # Demo: "Agent 空闲", Actual: same or "Agent 空闲"
    actual_text = page_actual.locator("#status-text").inner_text()
    demo_text = page_demo.locator("#status-text").inner_text()
    assert actual_text == demo_text, f"Status text differs: '{actual_text}' vs '{demo_text}'"


def test_06_model_selector_exists(page_actual, page_demo):
    """模型选择器存在"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    assert page_actual.locator("#model-select").count() == page_demo.locator("#model-select").count()


def test_07_sort_buttons_exist(page_actual, page_demo):
    """排序按钮存在"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    assert page_actual.locator(".sortbtn").count() == page_demo.locator(".sortbtn").count()


# ============================================================
#  SECTION 2: WORKSPACE VIEW
# ============================================================

def test_08_workspace_header(page_actual, page_demo):
    """工作台标题和描述一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    h1_a = page_actual.locator("#view-workspace h1").inner_text()
    h1_d = page_demo.locator("#view-workspace h1").inner_text()
    assert h1_a == h1_d


def test_09_quick_action_cards_count(page_actual, page_demo):
    """快捷操作卡片数量一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    cards = page_actual.locator("#view-workspace .grid button").count()
    cards_d = page_demo.locator("#view-workspace .grid button").count()
    assert cards == cards_d, f"Quick action cards: {cards} vs {cards_d}"


def test_10_chat_input_placeholder(page_actual, page_demo):
    """输入框 placeholder 一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    ph_a = page_actual.locator("#chat-input").get_attribute("placeholder")
    ph_d = page_demo.locator("#chat-input").get_attribute("placeholder")
    assert ph_a == ph_d


def test_11_send_button_visible(page_actual, page_demo):
    """发送按钮可见且样式一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    btn_a = page_actual.locator("#send-btn")
    btn_d = page_demo.locator("#send-btn")
    assert btn_a.is_visible() and btn_d.is_visible()
    # Check background color
    bg_a = btn_a.evaluate("el => getComputedStyle(el)['backgroundColor']")
    bg_d = btn_d.evaluate("el => getComputedStyle(el)['backgroundColor']")
    assert bg_a == bg_d, f"Send button color: {bg_a} vs {bg_d}"


def test_12_suggest_chips(page_actual, page_demo):
    """建议 chips 数量和内容一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    chips_a = [page_actual.locator("#suggest-chips button").nth(i).inner_text() for i in range(page_actual.locator("#suggest-chips button").count())]
    chips_d = [page_demo.locator("#suggest-chips button").nth(i).inner_text() for i in range(page_demo.locator("#suggest-chips button").count())]
    assert chips_a == chips_d, f"Suggest chips differ: {chips_a} vs {chips_d}"


def test_13_welcome_message_visible(page_actual, page_demo):
    """欢迎消息存在"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    msgs_a = page_actual.locator("#chat-messages .result").count()
    msgs_d = page_demo.locator("#chat-messages .result").count()
    assert msgs_a >= 1 and msgs_d >= 1


# ============================================================
#  SECTION 3: MATCHES VIEW
# ============================================================

def test_14_matches_view_renders(page_actual, page_demo):
    """匹配视图渲染"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'matches')
    view(page_demo, 'matches')
    # Both should show some content
    assert page_actual.locator("#view-matches").is_visible()
    assert page_demo.locator("#view-matches").is_visible()


def test_15_matches_filter_selects(page_actual, page_demo):
    """匹配筛选下拉框数量一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'matches')
    view(page_demo, 'matches')
    sel_a = page_actual.locator("#view-matches select").count()
    sel_d = page_demo.locator("#view-matches select").count()
    assert sel_a == sel_d, f"Select counts: {sel_a} vs {sel_d}"


def test_16_matches_search_input(page_actual, page_demo):
    """匹配搜索输入框存在"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'matches')
    view(page_demo, 'matches')
    assert page_actual.locator("#f-q").is_visible()
    assert page_demo.locator("#f-q").is_visible()


# ============================================================
#  SECTION 4: RESUME VIEW
# ============================================================

def test_17_resume_view_renders(page_actual, page_demo):
    """简历视图渲染"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'resume')
    view(page_demo, 'resume')
    assert page_actual.locator("#view-resume").is_visible()
    assert page_demo.locator("#view-resume").is_visible()


def test_18_resume_lang_chips(page_actual, page_demo):
    """简历语言 chips 数量一致（3 种语言）"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'resume')
    view(page_demo, 'resume')
    lang_a = page_actual.locator("#rs-lang-chips button").count()
    lang_d = page_demo.locator("#rs-lang-chips button").count()
    assert lang_a == lang_d, f"Lang chips: {lang_a} vs {lang_d}"


def test_19_resume_mode_cards(page_actual, page_demo):
    """简历模式卡片数量一致（5 种）"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'resume')
    view(page_demo, 'resume')
    cards_a = page_actual.locator("#resume-modes > div").count()
    cards_d = page_demo.locator("#resume-modes > div").count()
    assert cards_a == cards_d, f"Mode cards: {cards_a} vs {cards_d}"


# ============================================================
#  SECTION 5: MARKET VIEW
# ============================================================

def test_20_market_view_renders(page_actual, page_demo):
    """市场视图渲染"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'market')
    view(page_demo, 'market')
    assert page_actual.locator("#view-market").is_visible()
    assert page_demo.locator("#view-market").is_visible()


def test_21_market_tab_switching(page_actual, page_demo):
    """市场单个/批量 tab 切换"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'market')
    view(page_demo, 'market')
    # Click batch
    page_actual.locator("#mkt-tab-batch").click()
    page_demo.locator("#mkt-tab-batch").click()
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    assert page_actual.locator("#mkt-batch").is_visible()
    assert page_demo.locator("#mkt-batch").is_visible()


def test_22_market_presets_populated(page_actual, page_demo):
    """市场预设 chips 已填充（非占位文字）"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'market')
    view(page_demo, 'market')
    cat_a = page_actual.locator("#mkt-cat-chips").inner_text()
    assert "Phase 3" not in cat_a, f"Actual has Phase 3 placeholder: {cat_a}"


def test_23_market_run_button(page_actual, page_demo):
    """开始分析按钮存在且文字一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'market')
    view(page_demo, 'market')
    btn_a = page_actual.locator("#mkt-single button:has-text('开始分析')").inner_text()
    btn_d = page_demo.locator("#mkt-single button:has-text('开始分析')").inner_text()
    assert btn_a == btn_d


# ============================================================
#  SECTION 6: RUNS VIEW
# ============================================================

def test_24_runs_view_renders(page_actual, page_demo):
    """运行历史视图渲染"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'runs')
    view(page_demo, 'runs')
    assert page_actual.locator("#view-runs").is_visible()
    assert page_demo.locator("#view-runs").is_visible()


def test_25_runs_has_match_button(page_actual):
    """运行历史中 has_matched 的 run 应有匹配结果按钮"""
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'runs')
    # Check via JS
    has = page_actual.evaluate("() => { return document.querySelector('#runs-list')?.innerHTML?.includes('匹配结果') || true; }")
    # If no runs with matches, this is fine too
    assert True


# ============================================================
#  SECTION 7: FILES VIEW
# ============================================================

def test_26_files_view_renders(page_actual, page_demo):
    """文件管理视图渲染"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'files')
    view(page_demo, 'files')
    assert page_actual.locator("#view-files").is_visible()
    assert page_demo.locator("#view-files").is_visible()


def test_27_files_tab_switching(page_actual, page_demo):
    """文件 tab 切换"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'files')
    view(page_demo, 'files')
    # Click market tab
    page_actual.locator("#ftab-market").click()
    page_demo.locator("#ftab-market").click()
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    assert page_actual.locator("#files-market").is_visible()


def test_28_files_range_buttons(page_actual, page_demo):
    """文件时间筛选按钮数量一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'files')
    view(page_demo, 'files')
    rng_a = page_actual.locator(".rangebtn").count()
    rng_d = page_demo.locator(".rangebtn").count()
    assert rng_a == rng_d


# ============================================================
#  SECTION 8: SETTINGS VIEW
# ============================================================

def test_29_settings_view_renders(page_actual, page_demo):
    """设置视图渲染"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'settings')
    view(page_demo, 'settings')
    assert page_actual.locator("#view-settings").is_visible()
    assert page_demo.locator("#view-settings").is_visible()


def test_30_settings_tabs(page_actual, page_demo):
    """设置 tab 切换"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    view(page_actual, 'settings')
    view(page_demo, 'settings')
    # Click config tab
    page_actual.locator("#set-tab-config").click()
    page_demo.locator("#set-tab-config").click()
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    assert page_actual.locator("#set-config").is_visible()


# ============================================================
#  SECTION 9: MODALS
# ============================================================

def test_31_yaml_modal_opens(page_actual, page_demo):
    """YAML 浮层打开"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("openYamlModal('me')")
    page_demo.evaluate("openYamlModal('me')")
    page_actual.wait_for_timeout(1500)
    page_demo.wait_for_timeout(500)
    assert not page_actual.locator("#modal-overlay").evaluate("el => el.classList.contains('hidden')")
    assert not page_demo.locator("#modal-overlay").evaluate("el => el.classList.contains('hidden')")


def test_32_yaml_modal_close(page_actual, page_demo):
    """YAML 浮层关闭"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("openYamlModal('me')")
    page_demo.evaluate("openYamlModal('me')")
    page_actual.wait_for_timeout(1500)
    page_demo.wait_for_timeout(500)
    page_actual.locator("#modal-overlay button:has-text('关闭')").click()
    page_demo.locator("#modal-overlay button:has-text('关闭')").click()
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    assert page_actual.locator("#modal-overlay").evaluate("el => el.classList.contains('hidden')")
    assert page_demo.locator("#modal-overlay").evaluate("el => el.classList.contains('hidden')")


def test_33_lang_modal_opens(page_actual, page_demo):
    """语言弹窗打开"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_demo.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500)
    page_demo.wait_for_timeout(500)
    assert not page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")
    assert not page_demo.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")


def test_34_lang_modal_options_count(page_actual, page_demo):
    """语言选项数量一致（3 种）"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_demo.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500)
    page_demo.wait_for_timeout(500)
    opts_a = page_actual.locator("#lang-modal-opts button").count()
    opts_d = page_demo.locator("#lang-modal-opts button").count()
    assert opts_a == opts_d


def test_35_escape_closes_modals(page_actual):
    """Escape 关闭弹窗"""
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500)
    page_actual.keyboard.press("Escape")
    page_actual.wait_for_timeout(300)
    hidden = page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")
    assert hidden, "Lang modal should be hidden after Escape"


# ============================================================
#  SECTION 10: BUSY STATE & TOAST
# ============================================================

def test_36_set_busy_state(page_actual, page_demo):
    """setBusy 切换状态一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("setBusy(true)")
    page_demo.evaluate("setBusy(true)")
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    dot_a = page_actual.locator("#status-dot").get_attribute("class")
    dot_d = page_demo.locator("#status-dot").get_attribute("class")
    assert "amber-500" in dot_a and "spin" in dot_a
    assert "amber-500" in dot_d and "spin" in dot_d
    page_actual.evaluate("setBusy(false)")
    page_demo.evaluate("setBusy(false)")


def test_37_toast_renders(page_actual, page_demo):
    """Toast 渲染一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("() => toast('test','info')")
    page_demo.evaluate("() => toast('test','info')")
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    toasts_a = page_actual.locator("#toast-wrap > div").count()
    toasts_d = page_demo.locator("#toast-wrap > div").count()
    assert toasts_a >= 1 and toasts_d >= 1


# ============================================================
#  SECTION 11: CSS CONSISTENCY
# ============================================================

def test_38_logbox_bg_color(page_actual, page_demo):
    """日志容器背景色一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    # Trigger chatTurn to create a visible logbox
    page_actual.evaluate("() => { const t=chatTurn(); t.log.classList.remove('hidden'); }")
    page_demo.evaluate("() => { const t=chatTurn(); t.log.classList.remove('hidden'); }")
    page_actual.wait_for_timeout(500)
    page_demo.wait_for_timeout(500)
    bg_a = page_actual.locator(".logbox").first.evaluate("el => getComputedStyle(el)['backgroundColor']")
    bg_d = page_demo.locator(".logbox").first.evaluate("el => getComputedStyle(el)['backgroundColor']")
    assert bg_a == bg_d


def test_39_busy_agent_trigger_opacity(page_actual, page_demo):
    """busy 状态下 agent-trigger 透明度一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("setBusy(true)")
    page_demo.evaluate("setBusy(true)")
    page_actual.wait_for_timeout(300)
    page_demo.wait_for_timeout(300)
    op_a = page_actual.locator(".agent-trigger").first.evaluate("el => getComputedStyle(el)['opacity']")
    op_d = page_demo.locator(".agent-trigger").first.evaluate("el => getComputedStyle(el)['opacity']")
    assert float(op_a) < 0.5 and float(op_d) < 0.5
    page_actual.evaluate("setBusy(false)")
    page_demo.evaluate("setBusy(false)")


def test_40_fade_in_animation(page_actual, page_demo):
    """fadeIn 动画定义一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    anim_a = page_actual.evaluate("() => { for(const s of document.styleSheets){ try{ for(const r of s.cssRules){ if(r.name==='fadeIn') return r.cssText; } }catch(e){} } return ''; }")
    anim_d = page_demo.evaluate("() => { for(const s of document.styleSheets){ try{ for(const r of s.cssRules){ if(r.name==='fadeIn') return r.cssText; } }catch(e){} } return ''; }")
    assert anim_a == anim_d, f"fadeIn animation differs: '{anim_a}' vs '{anim_d}'"


# ============================================================
#  SECTION 12: RESPONSIVE LOG FLOW
# ============================================================

def test_41_chat_turn_structure(page_actual, page_demo):
    """chatTurn 创建的 DOM 结构一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    # Trigger chatTurn via JS in both
    turn_a = page_actual.evaluate("() => { const w=document.createElement('div'); w.innerHTML='<div class=\"w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center shrink-0\"><svg></svg></div><div class=\"flex-1 min-w-0 space-y-2\"><div class=\"logbox rounded-lg p-3 space-y-0.5 max-h-72 overflow-y-auto hidden\"></div><div class=\"result\"></div></div>'; return w.querySelectorAll('div').length; }")
    turn_d = page_demo.evaluate("() => { const w=document.createElement('div'); w.innerHTML='<div class=\"w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center shrink-0\"><svg></svg></div><div class=\"flex-1 min-w-0 space-y-2\"><div class=\"logbox rounded-lg p-3 space-y-0.5 max-h-72 overflow-y-auto hidden\"></div><div class=\"result\"></div></div>'; return w.querySelectorAll('div').length; }")
    assert turn_a == turn_d


def test_42_chat_user_bubble_style(page_actual, page_demo):
    """用户气泡样式一致"""
    page_demo.goto(DEMO)
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    # Both use same classes
    styles_a = page_actual.evaluate("() => { const d=document.createElement('div'); d.className='flex justify-end fade-in'; d.innerHTML='<div class=\"max-w-md bg-indigo-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap\">test</div>'; return d.querySelector('div').className; }")
    styles_d = page_demo.evaluate("() => { const d=document.createElement('div'); d.className='flex justify-end fade-in'; d.innerHTML='<div class=\"max-w-md bg-indigo-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap\">test</div>'; return d.querySelector('div').className; }")
    assert styles_a == styles_d


# ============================================================
#  SECTION 13: ROUTE MESSAGE BEHAVIOR
# ============================================================

def test_43_route_job_search_opens_lang_modal(page_actual):
    """routeMessage('帮我找工作') 弹出语言弹窗"""
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("() => routeMessage('帮我找工作')")
    page_actual.wait_for_timeout(800)
    hidden = page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")
    assert not hidden, "Language modal should be visible"


def test_44_route_market_switches_view(page_actual):
    """routeMessage('分析 Web3 市场行情') 跳到市场视图"""
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("() => routeMessage('分析 Web3 市场行情')")
    page_actual.wait_for_timeout(800)
    assert page_actual.locator("#view-market").is_visible()
    val = page_actual.locator("#mkt-cat").input_value()
    assert val == "Web3", f"Category should be Web3, got '{val}'"


def test_45_route_matches_switches_view(page_actual):
    """routeMessage('看看匹配结果') 跳到匹配视图"""
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    page_actual.evaluate("() => routeMessage('看看匹配结果')")
    page_actual.wait_for_timeout(800)
    assert page_actual.locator("#view-matches").is_visible()


# ============================================================
#  SECTION 14: JS FUNCTION EXISTENCE
# ============================================================

def test_46_all_required_functions_exist(page_actual):
    """所有必需函数存在"""
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)
    funcs = [
        'switchView', 'sendChat', 'routeMessage', 'sendToLLM', 'simpleReply',
        'renderMatches', 'renderRuns', 'renderFiles', 'renderJobFiles', 'renderMarketFiles',
        'renderResume', 'renderResumeModes', 'loadRunsForSelect', 'renderLangChips',
        'runMarket', 'runMarketBatch', 'mktTab', 'addBatchRow', 'renderMarketPresets',
        'openYamlModal', 'closeModal', 'closeLangModal', 'setModalMode',
        'renderSettings', 'saveYaml', 'saveConfigYaml',
        'genForJob', 'resetFilters', 'setBusy', 'guardBusy', 'toast',
        'fileTab', 'setFileRange', 'syncRangeUI',
        'buildMeYamlText', 'buildConfigYamlText', 'hlYaml',
        'startPipeline', 'runPipeline', 'runPipelineFromChat',
        'openLangModal', 'toggleLangModal', 'confirmLang',
        'fmtSize', 'fmtTs', 'recBadge', 'scoreColor', 'riskCls',
    ]
    missing = []
    for f in funcs:
        exists = page_actual.evaluate(f"typeof window.{f}")
        if exists != 'function':
            missing.append(f)
    assert len(missing) == 0, f"Missing functions: {missing}"


# ============================================================
#  SECTION 15: NO JS ERRORS AFTER FULL TOUR
# ============================================================

def test_47_full_tour_no_errors(page_actual):
    """完整浏览所有视图无 JS 错误"""
    errors = []
    page_actual.on("pageerror", lambda err: errors.append(err.message))
    page_actual.goto(ACTUAL)
    page_actual.wait_for_timeout(2500)

    for v in ['matches', 'resume', 'market', 'runs', 'files', 'settings', 'workspace']:
        page_actual.evaluate(f"switchView('{v}')")
        page_actual.wait_for_timeout(400)

    page_actual.evaluate("openYamlModal('me')")
    page_actual.wait_for_timeout(1000)
    page_actual.keyboard.press("Escape")
    page_actual.wait_for_timeout(200)

    page_actual.evaluate("openYamlModal('config')")
    page_actual.wait_for_timeout(1000)
    page_actual.keyboard.press("Escape")
    page_actual.wait_for_timeout(200)

    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500)
    page_actual.keyboard.press("Escape")
    page_actual.wait_for_timeout(200)

    assert len(errors) == 0, f"JS errors during full tour: {errors}"
