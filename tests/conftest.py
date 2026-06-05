"""conftest.py — fixtures with fast config, deepseek, and proper page setup."""
import pytest
import shutil
import os
from playwright.sync_api import sync_playwright

PROFILES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
ORIG_CONFIG = os.path.join(PROFILES, "search_config.yaml")
FAST_CONFIG = os.path.join(PROFILES, "search_config_fast.yaml")
BACKUP_CONFIG = os.path.join(PROFILES, "search_config_backup.yaml")

ACTUAL = "http://127.0.0.1:5000"
DEMO = "file:///D:/job-agent/new-ui/index.html"
VP = {"width": 1280, "height": 800}


def _activate_fast_config():
    if not os.path.exists(FAST_CONFIG):
        return False
    shutil.copy2(ORIG_CONFIG, BACKUP_CONFIG)
    shutil.copy2(FAST_CONFIG, ORIG_CONFIG)
    return True


def _restore_config():
    if os.path.exists(BACKUP_CONFIG):
        shutil.copy2(BACKUP_CONFIG, ORIG_CONFIG)
        os.remove(BACKUP_CONFIG)


@pytest.fixture(scope="session", autouse=True)
def manage_config():
    ok = _activate_fast_config()
    yield
    if ok:
        _restore_config()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _setup_page(page, url, wait_ms=2500):
    page.set_viewport_size(VP)
    page.goto(url)
    page.wait_for_timeout(wait_ms)
    page.add_style_tag(content="*, *::before, *::after { animation: none !important; transition: none !important; }")
    # For actual (API) pages, wait for session and switch to deepseek
    if "127.0.0.1" in url or "localhost" in url:
        try:
            page.wait_for_function("() => document.querySelector('#status-text')?.textContent === 'Agent 空闲'", timeout=12000)
        except:
            pass
        page.evaluate("() => { var s=document.querySelector('#model-select'); if(s){ s.value='deepseek'; s.dispatchEvent(new Event('change')); } }")
        page.wait_for_timeout(800)


@pytest.fixture
def page_actual(browser):
    ctx = browser.new_context(viewport=VP)
    page = ctx.new_page()
    _setup_page(page, ACTUAL)
    yield page
    ctx.close()


@pytest.fixture
def page_demo(browser):
    ctx = browser.new_context(viewport=VP)
    page = ctx.new_page()
    _setup_page(page, DEMO, wait_ms=800)
    yield page
    ctx.close()
