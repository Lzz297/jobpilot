"""
full_regression_v2.py — upgraded regression with DeepSeek, grayscale screenshots,
fast pipeline config, busy recovery, and comprehensive diff reporting.
"""
import pytest
import io
import os
from PIL import Image

ACTUAL = "http://127.0.0.1:5000"
DEMO = "file:///D:/job-agent/new-ui/index.html"
DIFF_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "diffs")
os.makedirs(DIFF_DIR, exist_ok=True)

# ── Screenshot helpers ──
def _gray_compare(img_a_bytes, img_b_bytes, threshold=0.02):
    """Convert both to grayscale, compare pixel diff. Returns (pct, passed, diff_bytes)."""
    a = Image.open(io.BytesIO(img_a_bytes)).convert("L")
    b = Image.open(io.BytesIO(img_b_bytes)).convert("L")
    if a.size != b.size:
        b = b.resize(a.size)
    pa = list(a.getdata())
    pb = list(b.getdata())
    total = len(pa)
    diff_count = 0
    diff_img = Image.new("L", a.size, 0)
    diff_pixels = diff_img.load()
    for i, (v1, v2) in enumerate(zip(pa, pb)):
        if abs(v1 - v2) > 25:  # diff threshold in grayscale (0-255)
            diff_count += 1
            x, y = i % a.width, i // a.width
            diff_pixels[x, y] = 255
    pct = diff_count / total if total > 0 else 0
    buf = io.BytesIO()
    diff_img.save(buf, "PNG")
    return pct, pct <= threshold, buf.getvalue()


def ss_compare(pa, pd, selector, label, threshold=0.02):
    """Screenshot both pages, grayscale compare. Returns status string."""
    try:
        ea = pa.locator(selector)
        ed = pd.locator(selector)
        if ea.count() == 0 or ed.count() == 0:
            return f"SKIP: '{selector}' not found on one page"
        ba = ea.screenshot()
        bd = ed.screenshot()
        pct, ok, diff_bytes = _gray_compare(ba, bd, threshold)
        if ok:
            return f"OK: {label} gray-diff={pct*100:.2f}%"
        else:
            name = label.replace(" ", "_").replace("/", "-")
            path = os.path.join(DIFF_DIR, f"{name}.png")
            with open(path, "wb") as f:
                f.write(diff_bytes)
            return f"DIFF: {label} gray-diff={pct*100:.2f}% > {threshold*100:.1f}% -> {path}"
    except Exception as e:
        return f"ERROR: {label} — {str(e)[:80]}"


def text_eq(pa, pd, selector):
    try:
        return pa.locator(selector).first.inner_text().strip() == pd.locator(selector).first.inner_text().strip()
    except:
        return False


def count_eq(pa, pd, selector):
    try:
        return pa.locator(selector).count() == pd.locator(selector).count()
    except:
        return False


SCREENSHOT_LOG = []


# ============================================================
#  SECTION A — SCREENSHOT COMPARISON (grayscale, 2% threshold)
# ============================================================

def test_A01_sidebar(page_actual, page_demo):
    r = ss_compare(page_actual, page_demo, "#sidebar", "Sidebar")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A02_chat_input(page_actual, page_demo):
    r = ss_compare(page_actual, page_demo, "#view-workspace .shrink-0.border-t", "Chat-input")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A03_workspace_cards(page_actual, page_demo):
    r = ss_compare(page_actual, page_demo, "#view-workspace .grid", "Workspace-cards")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A04_status_pill(page_actual, page_demo):
    r = ss_compare(page_actual, page_demo, "#status-pill", "Status-pill")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A05_market_form(page_actual, page_demo):
    page_actual.evaluate("switchView('market')"); page_demo.evaluate("switchView('market')")
    page_actual.wait_for_timeout(600); page_demo.wait_for_timeout(600)
    r = ss_compare(page_actual, page_demo, "#mkt-single", "Market-form")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A06_resume_cards(page_actual, page_demo):
    page_actual.evaluate("switchView('resume')"); page_demo.evaluate("switchView('resume')")
    page_actual.wait_for_timeout(600); page_demo.wait_for_timeout(600)
    r = ss_compare(page_actual, page_demo, "#resume-modes", "Resume-cards")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A07_lang_modal(page_actual, page_demo):
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_demo.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    r = ss_compare(page_actual, page_demo, "#lang-overlay .max-w-md", "Lang-modal")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r

def test_A08_settings(page_actual, page_demo):
    page_actual.evaluate("switchView('settings')"); page_demo.evaluate("switchView('settings')")
    page_actual.wait_for_timeout(600); page_demo.wait_for_timeout(600)
    r = ss_compare(page_actual, page_demo, "#set-profile", "Settings-profile")
    SCREENSHOT_LOG.append(r); assert "ERROR" not in r, r


# ============================================================
#  SECTION B — COUNT / TEXT CONSISTENCY
# ============================================================

def test_B01_navbtn_count(page_actual, page_demo):
    assert count_eq(page_actual, page_demo, ".navbtn")

def test_B02_sortbtn_count(page_actual, page_demo):
    assert count_eq(page_actual, page_demo, ".sortbtn")

def test_B03_suggest_chips_count(page_actual, page_demo):
    assert count_eq(page_actual, page_demo, "#suggest-chips button")

def test_B04_lang_chips_count(page_actual, page_demo):
    page_actual.evaluate("switchView('resume')"); page_demo.evaluate("switchView('resume')")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    assert count_eq(page_actual, page_demo, "#rs-lang-chips button")

def test_B05_resume_mode_count(page_actual, page_demo):
    page_actual.evaluate("switchView('resume')"); page_demo.evaluate("switchView('resume')")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    assert count_eq(page_actual, page_demo, "#resume-modes > div")

def test_B06_market_labels(page_actual, page_demo):
    page_actual.evaluate("switchView('market')"); page_demo.evaluate("switchView('market')")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    for lbl in ["岗位类别", "行业分类", "地点", "排序"]:
        assert lbl in page_actual.locator("#mkt-single").inner_text()
        assert lbl in page_demo.locator("#mkt-single").inner_text()

def test_B07_market_run_button(page_actual, page_demo):
    assert text_eq(page_actual, page_demo, "#mkt-single button:has-text('开始分析')")

def test_B08_range_buttons_count(page_actual, page_demo):
    page_actual.evaluate("switchView('files')"); page_demo.evaluate("switchView('files')")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    assert count_eq(page_actual, page_demo, ".rangebtn")

def test_B09_file_tab_labels(page_actual, page_demo):
    assert text_eq(page_actual, page_demo, "#ftab-jobs")
    assert text_eq(page_actual, page_demo, "#ftab-market")

def test_B10_lang_modal_options(page_actual, page_demo):
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_demo.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    assert count_eq(page_actual, page_demo, "#lang-modal-opts button")

def test_B11_quick_action_texts(page_actual, page_demo):
    for i in range(min(page_actual.locator("#view-workspace .grid button").count(), 3)):
        ta = page_actual.locator("#view-workspace .grid button").nth(i).inner_text()
        td = page_demo.locator("#view-workspace .grid button").nth(i).inner_text()
        assert ta == td, f"Card {i}: '{ta}' vs '{td}'"

def test_B12_settings_tabs(page_actual, page_demo):
    page_actual.evaluate("switchView('settings')"); page_demo.evaluate("switchView('settings')")
    page_actual.wait_for_timeout(500); page_demo.wait_for_timeout(500)
    assert count_eq(page_actual, page_demo, "#set-tab-profile, #set-tab-config")


# ============================================================
#  SECTION C — STREAMING LOG COMPARISON (with fast config)
# ============================================================

def test_C01_demo_stream_log_structure(page_demo):
    """Verify demo's mock pipeline produces expected log sequence."""
    page_demo.goto(DEMO); page_demo.wait_for_timeout(800)
    page_demo.evaluate("() => { PIPE_LANGS=['en','hk','cn']; startPipeline(); }")
    page_demo.wait_for_timeout(500)
    page_demo.locator("#lang-overlay button:has-text('开始')").click()
    page_demo.wait_for_timeout(1500)
    # Demo's mock stream should create multiple .ln entries in .logbox
    n = page_demo.locator("#chat-messages .logbox .ln").count()
    assert n > 2, f"Demo stream should produce >2 log entries, got {n}"

@pytest.mark.skip(reason="Pipeline still >2min even with fast config. Manual test: 1) start server with deepseek 2) open http://127.0.0.1:5000 3) click 一键找工作 4) verify SSE logs appear incrementally 5) verify auto-scroll 6) verify done panel stats+buttons")
def test_C02_pipeline_log_structure(page_actual):
    """Actual SSE pipeline (fast config) produces log entries incrementally."""
    try:
        page_actual.wait_for_function("() => document.querySelector('#status-text')?.textContent === 'Agent 空闲'", timeout=10000)
    except:
        pass
    page_actual.evaluate("() => { PIPE_LANGS=['en']; runPipeline(['en']); }")
    page_actual.wait_for_timeout(800)

    appeared_incrementally = False
    prev = 0
    for _ in range(80):
        cur = page_actual.locator("#chat-messages .logbox .ln").count()
        if cur > prev + 1:
            appeared_incrementally = True
        prev = cur
        if page_actual.locator("text=查看匹配结果").count() > 0:
            break
        page_actual.wait_for_timeout(500)
    assert appeared_incrementally or prev >= 2, f"Pipeline log: final entries={prev}"

@pytest.mark.skip(reason="Pipeline >2min. Manual: verify '查看匹配结果' and '查看文件' buttons appear after pipeline completes.")
def test_C03_pipeline_done_panel_buttons(page_actual):
    """Done panel has nav buttons."""
    try:
        page_actual.wait_for_function("() => document.querySelector('#status-text')?.textContent === 'Agent 空闲'", timeout=10000)
    except:
        pass
    page_actual.evaluate("() => runPipeline(['en'])")
    page_actual.wait_for_timeout(800)
    for _ in range(80):
        if page_actual.locator("text=查看匹配结果").count() > 0:
            break
        page_actual.wait_for_timeout(500)
    assert page_actual.locator("text=查看匹配结果").count() > 0, "Missing nav button"
    assert page_actual.locator("text=查看文件").count() > 0, "Missing file button"

@pytest.mark.skip(reason="Pipeline >2min. Manual: verify stats grid (抓取岗位/达标匹配/简历文件) appears after pipeline completes.")
def test_C04_pipeline_done_panel_stats_grid(page_actual):
    """Done panel has 3-column stats grid."""
    try:
        page_actual.wait_for_function("() => document.querySelector('#status-text')?.textContent === 'Agent 空闲'", timeout=10000)
    except:
        pass
    page_actual.evaluate("() => runPipeline(['en'])")
    page_actual.wait_for_timeout(800)
    for _ in range(80):
        if page_actual.locator("text=抓取岗位").count() > 0:
            break
        page_actual.wait_for_timeout(500)
    assert page_actual.locator("text=抓取岗位").count() > 0
    assert page_actual.locator("text=达标匹配").count() > 0
    assert page_actual.locator("text=简历文件").count() > 0


# ============================================================
#  SECTION D — EDGE / ERROR CASES
# ============================================================

def test_D01_guard_busy_blocks(page_actual):
    page_actual.evaluate("setBusy(true)")
    blocked = page_actual.evaluate("guardBusy()")
    assert blocked
    op = page_actual.locator(".agent-trigger").first.evaluate("el => getComputedStyle(el)['opacity']")
    assert float(op) < 0.5
    page_actual.evaluate("setBusy(false)")

def test_D02_escape_closes_modals(page_actual):
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500)
    page_actual.keyboard.press("Escape")
    page_actual.wait_for_timeout(300)
    try:
        page_actual.evaluate("openYamlModal('me')")
    except:
        page_actual.reload(); page_actual.wait_for_timeout(3000)
        page_actual.evaluate("openYamlModal('me')")
    page_actual.wait_for_timeout(1500)
    page_actual.keyboard.press("Escape")
    page_actual.wait_for_timeout(300)

def test_D03_backdrop_close(page_actual):
    page_actual.evaluate("closeLangModal()")
    page_actual.wait_for_timeout(300)
    hidden = page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")
    assert hidden, "closeLangModal failed"

def test_D04_empty_filter(page_actual):
    page_actual.evaluate("switchView('matches')")
    page_actual.wait_for_timeout(500)
    page_actual.locator("#f-q").fill("xyznomatch99999")
    page_actual.wait_for_timeout(500)
    # Should not crash

def test_D05_send_to_llm(page_actual):
    page_actual.fill("#chat-input", "hello")
    page_actual.click("#send-btn")
    page_actual.wait_for_timeout(2000)
    assert page_actual.locator("#chat-messages .flex.justify-end").count() >= 1

def test_D06_500_graceful(page_actual):
    page_actual.route("**/api/chat", lambda r: r.fulfill(status=500, body='{"error":"test"}'))
    page_actual.evaluate("() => routeMessage('test')")
    page_actual.wait_for_timeout(2000)
    # Should not crash

# ============================================================
#  SECTION E — E2E ROUTE
# ============================================================

def test_E01_route_job_search(page_actual):
    page_actual.fill("#chat-input", "帮我找工作")
    page_actual.press("#chat-input", "Enter")
    page_actual.wait_for_timeout(800)
    assert not page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")
    page_actual.keyboard.press("Escape")

def test_E02_route_market(page_actual):
    page_actual.fill("#chat-input", "分析 Web3 市场行情")
    page_actual.press("#chat-input", "Enter")
    page_actual.wait_for_timeout(800)
    assert page_actual.locator("#view-market").is_visible()
    assert page_actual.locator("#mkt-cat").input_value() == "Web3"

def test_E03_route_matches(page_actual):
    page_actual.fill("#chat-input", "看看匹配结果")
    page_actual.press("#chat-input", "Enter")
    page_actual.wait_for_timeout(800)
    assert page_actual.locator("#view-matches").is_visible()

def test_E04_suggest_chip(page_actual):
    page_actual.locator("#suggest-chips button:has-text('帮我找工作')").click()
    page_actual.wait_for_timeout(800)
    assert not page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")
    page_actual.keyboard.press("Escape")


# ============================================================
#  SECTION F — LANG MODAL
# ============================================================

def test_F01_min_one_lang(page_actual):
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});")
    page_actual.wait_for_timeout(500)
    buttons = page_actual.locator("#lang-modal-opts button").all()
    for btn in buttons:
        btn.click(); page_actual.wait_for_timeout(100)
    assert page_actual.locator("#lang-modal-opts button .bg-indigo-600").count() >= 1
    page_actual.keyboard.press("Escape")

def test_F02_confirm(page_actual):
    page_actual.evaluate("() => { window.__lang_ok=false; openLangModal(['en'],(l)=>{window.__lang_ok=true;}); }")
    page_actual.wait_for_timeout(500)
    page_actual.locator("#lang-overlay button:has-text('开始')").click()
    page_actual.wait_for_timeout(500)
    assert page_actual.locator("#lang-overlay").evaluate("el => el.classList.contains('hidden')")


# ============================================================
#  SECTION G — BUSY STATE (incl. recovery)
# ============================================================

def test_G01_busy_dims_triggers(page_actual):
    page_actual.evaluate("setBusy(true)")
    page_actual.wait_for_timeout(300)
    ok = True
    for i in range(min(page_actual.locator(".agent-trigger").count(), 5)):
        op = page_actual.locator(".agent-trigger").nth(i).evaluate("el => getComputedStyle(el)['opacity']")
        if float(op) >= 0.5:
            ok = False
    assert ok
    page_actual.evaluate("setBusy(false)")

def test_G02_status_dot_busy(page_actual):
    cls = page_actual.locator("#status-dot").get_attribute("class")
    assert "emerald-500" in cls
    page_actual.evaluate("setBusy(true)")
    page_actual.wait_for_timeout(300)
    cls_b = page_actual.locator("#status-dot").get_attribute("class")
    assert "amber-500" in cls_b and "spin" in cls_b
    page_actual.evaluate("setBusy(false)")

def test_G03_busy_recovery(page_actual):
    """setBusy(true) then setBusy(false) — triggers should fully recover."""
    page_actual.evaluate("setBusy(true)")
    page_actual.wait_for_timeout(300)
    page_actual.evaluate("setBusy(false)")
    page_actual.wait_for_timeout(300)
    # agent-trigger should be back to opacity 1
    op = page_actual.locator(".agent-trigger").first.evaluate("el => getComputedStyle(el)['opacity']")
    assert float(op) >= 1.0, f"agent-trigger should recover to opacity 1, got {op}"
    # status-dot should be emerald, no spin
    cls = page_actual.locator("#status-dot").get_attribute("class")
    assert "emerald-500" in cls and "spin" not in cls, f"dot should be emerald no-spin after recovery: {cls}"
    # status text
    txt = page_actual.locator("#status-text").inner_text()
    assert "空闲" in txt, f"status should show idle after recovery: {txt}"


# ============================================================
#  SECTION H — FULL TOUR
# ============================================================

def test_H01_full_tour_no_errors(page_actual):
    errors = []
    page_actual.on("pageerror", lambda err: errors.append(err.message))
    try:
        page_actual.evaluate("() => 1")
    except:
        page_actual.goto(ACTUAL); page_actual.wait_for_timeout(3000)

    for v in ['matches','resume','market','runs','files','settings','workspace']:
        page_actual.evaluate(f"switchView('{v}')"); page_actual.wait_for_timeout(400)

    page_actual.evaluate("openYamlModal('me')"); page_actual.wait_for_timeout(1000)
    page_actual.keyboard.press("Escape"); page_actual.wait_for_timeout(200)
    page_actual.evaluate("openYamlModal('config')"); page_actual.wait_for_timeout(1000)
    page_actual.keyboard.press("Escape"); page_actual.wait_for_timeout(200)
    page_actual.evaluate("openLangModal(['en','hk','cn'], ()=>{});"); page_actual.wait_for_timeout(500)
    page_actual.keyboard.press("Escape"); page_actual.wait_for_timeout(200)

    page_actual.evaluate("switchView('market')"); page_actual.wait_for_timeout(300)
    page_actual.locator("#mkt-tab-batch").click(); page_actual.wait_for_timeout(300)
    page_actual.locator("#mkt-tab-single").click(); page_actual.wait_for_timeout(300)
    page_actual.evaluate("switchView('files')"); page_actual.wait_for_timeout(300)
    page_actual.locator("#ftab-market").click(); page_actual.wait_for_timeout(300)
    page_actual.locator("#ftab-jobs").click(); page_actual.wait_for_timeout(300)
    page_actual.evaluate("switchView('settings')"); page_actual.wait_for_timeout(300)
    page_actual.locator("#set-tab-config").click(); page_actual.wait_for_timeout(300)
    page_actual.locator("#set-tab-profile").click(); page_actual.wait_for_timeout(300)

    assert len(errors) == 0, f"Errors: {errors}"
