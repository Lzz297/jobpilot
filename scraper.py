"""
scraper.py - JobsDB 岗位抓取模块（修复版）
支持三种解析策略：__NEXT_DATA__ / JSON-LD / HTML 直接解析
requests 被 403 时自动回退 Playwright 无头浏览器
增强：深度递归搜索 __NEXT_DATA__、多策略提取 title、HTML DOM 补充
"""
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from urllib.parse import urlparse, quote_plus

from config import emit

# ─────────────────────────────────────
# 全局配置
# ─────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-HK;q=0.8,zh;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

_session = requests.Session()
_session.headers.update(HEADERS)

import threading

_pw_instance = None
_pw_browser = None
_pw_thread_id = None


def _get_playwright_browser():
    global _pw_instance, _pw_browser, _pw_thread_id

    # 如果浏览器已存在但属于已死的线程，直接放弃旧实例
    # （旧线程已退出，尝试 close()/stop() 也会跨线程报错，不如不碰）
    if _pw_browser is not None and threading.get_ident() != _pw_thread_id:
        _pw_browser = None
        _pw_instance = None

    # 浏览器存在且属于当前线程 → 探活
    if _pw_browser is not None:
        try:
            _pw_browser.contexts  # 轻量探活
            return _pw_browser
        except Exception:
            emit("   🔄 Playwright 浏览器已失效，正在重启...")
            try:
                _pw_browser.close()
            except Exception:
                pass
            try:
                _pw_instance.stop()
            except Exception:
                pass
            _pw_browser = None
            _pw_instance = None

    from playwright.sync_api import sync_playwright
    _pw_instance = sync_playwright().start()
    _pw_browser = _pw_instance.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    _pw_thread_id = threading.get_ident()
    emit("   🌐 Playwright 浏览器已启动")
    return _pw_browser


def cleanup_playwright():
    global _pw_instance, _pw_browser, _pw_thread_id
    # 不在创建线程上（如 atexit 在主线程调用）→ 不碰旧对象，直接标记释放
    if _pw_browser is not None and threading.get_ident() != _pw_thread_id:
        _pw_browser = None
        _pw_instance = None
        return
    if _pw_browser:
        try:
            _pw_browser.close()
        except Exception:
            pass
        _pw_browser = None
    if _pw_instance:
        try:
            _pw_instance.stop()
        except Exception:
            pass
        _pw_instance = None


def _fetch_html(url: str, wait_ms: int = 3000, context=None) -> str | None:
    """
    获取页面 HTML。context 为 None 时每次创建新 context（旧行为）；
    传入 context 时复用它创建 page，不关闭 context（由调用方管理生命周期）。
    context 失效时返回 (None, None)，调用方可据此重建 context。
    """
    # JobsDB 一律 403 requests，直接用 Playwright
    for attempt in range(2):
        try:
            browser = _get_playwright_browser()
            own_context = (context is None)
            if own_context:
                ctx = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="en-HK",
                    viewport={"width": 1920, "height": 1080},
                )
            else:
                ctx = context
            page = ctx.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
            """)
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(wait_ms)
            content = page.content()
            if "challenge" in content.lower():
                emit(f"   ⏳ 等待 Cloudflare 挑战...")
                page.wait_for_timeout(5000)
                content = page.content()
            elif len(content) < 2000:
                emit(f"   ⏳ 页面加载中（当前 {len(content)} 字符），等待...")
                page.wait_for_timeout(5000)
                content = page.content()
            page.close()
            if own_context:
                ctx.close()
            if len(content) > 2000:
                return content
            else:
                emit(f"   ⚠️ Playwright 获取内容过短 ({len(content)} 字符)")
                if not own_context:
                    return None  # 复用的 context 可能已失效，返回 None 让调用方重建
                return None
        except Exception as e:
            if not own_context:
                # 复用 context 失败：关闭旧 context，返回 None 让调用方重建
                try:
                    ctx.close()
                except Exception:
                    pass
                emit(f"   ⚠️ 复用 context 失败: {e}，请调用方重建")
                return None
            if attempt == 0:
                emit(f"   🔄 Playwright 失败，重建浏览器重试: {e}")
                global _pw_instance, _pw_browser
                try:
                    _pw_browser.close()
                except Exception:
                    pass
                try:
                    _pw_instance.stop()
                except Exception:
                    pass
                _pw_browser = None
                _pw_instance = None
            else:
                emit(f"   ⚠️ Playwright 重试仍失败: {e}")
                return None


# ─────────────────────────────────────
# URL 工具
# ─────────────────────────────────────

def normalize_jobsdb_url(url: str) -> str:
    match = re.search(r'/job/(\d{5,})', url)
    if match:
        return f"https://hk.jobsdb.com/job/{match.group(1)}"
    return url


def is_listing_page(url: str) -> bool:
    path = urlparse(url).path.rstrip('/').lower()
    if re.search(r'-jobs$', path):
        return True
    if path.endswith('/jobs'):
        return True
    if '/jobs?' in url.lower():
        return True
    return False


def is_job_detail_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    if re.search(r'/job/\d{5,}', path):
        return True
    if re.search(r'/job/[\w-]+-\d{5,}', path):
        return True
    if '/job-article/' in path:
        return True
    return False


def classify_urls(urls: list) -> dict:
    result = {"detail": [], "listing": [], "other": []}
    for url in urls:
        if is_job_detail_url(url):
            result["detail"].append(url)
        elif is_listing_page(url):
            result["listing"].append(url)
        else:
            result["other"].append(url)
    return result


# ─────────────────────────────────────
# __NEXT_DATA__ 深度解析工具
# ─────────────────────────────────────

def _find_jobs_array(data, max_depth=10):
    """
    在 __NEXT_DATA__ 中递归查找 jobs 数组。
    兼容各种嵌套结构（searchResults.data、dehydratedState.queries 等）。
    """

    def _is_jobs_array(arr):
        if not isinstance(arr, list) or len(arr) == 0:
            return False
        sample = arr[0]
        if not isinstance(sample, dict):
            return False
        job_id_keys = {'id', 'jobId', 'job_id', 'listingId'}
        return bool(job_id_keys & set(sample.keys()))

    def _search(obj, depth=0):
        if depth > max_depth:
            return None

        if isinstance(obj, list):
            if _is_jobs_array(obj):
                return obj
            # 处理 GraphQL edges 模式: [{node: {...}}, ...]
            if (len(obj) > 0 and isinstance(obj[0], dict)
                    and 'node' in obj[0]
                    and isinstance(obj[0]['node'], dict)):
                nodes = [item['node'] for item in obj
                         if isinstance(item.get('node'), dict)]
                if _is_jobs_array(nodes):
                    return nodes
            # 搜索数组中的每个元素
            for item in obj[:3]:
                if isinstance(item, (dict, list)):
                    found = _search(item, depth + 1)
                    if found:
                        return found

        if isinstance(obj, dict):
            # 优先尝试已知的 key
            priority_keys = [
                'data', 'jobs', 'results', 'jobList', 'searchResults',
                'edges', 'nodes', 'items', 'content', 'searches',
                'jobCards', 'listings', 'searchResult',
            ]
            for key in priority_keys:
                if key in obj:
                    found = _search(obj[key], depth + 1)
                    if found:
                        return found
            # 然后尝试所有其他 key
            for key in sorted(obj.keys()):
                if key in priority_keys:
                    continue
                val = obj[key]
                if isinstance(val, (dict, list)):
                    found = _search(val, depth + 1)
                    if found:
                        return found

        return None

    return _search(data) or []


# ─────────────────────────────────────
# 数据驱动的通用字段提取器
# ─────────────────────────────────────

_FIELD_SPECS = {
    "title": {
        "direct_keys": ["title", "jobTitle", "displayTitle", "heading",
                        "roleTitle", "name", "positionTitle"],
        "parent_keys": ["job", "content", "details", "jobDetail",
                        "listing", "jobInfo", "advertisement",
                        "solMetadata", "metadata"],
        "sub_keys": ["title", "jobTitle", "displayTitle", "heading", "name", "roleTitle"],
        "dict_sub_keys": [],
        "recursive": True,
        "recursive_keys": ["title", "jobTitle"],
        "max_depth": 3,
        "min_len": 2,
    },
    "id": {
        "direct_keys": ["id", "jobId", "job_id", "listingId"],
        "parent_keys": ["job", "content", "listing"],
        "sub_keys": ["id", "jobId"],
        "dict_sub_keys": [],
        "coerce_str": True,
    },
    "company": {
        "direct_keys": ["companyName", "company", "companyMeta"],
        "parent_keys": ["advertiser", "job", "content", "listing"],
        "sub_keys": ["description", "name", "companyName"],
        "dict_sub_keys": ["name", "description", "label", "display"],
    },
    "salary": {
        "direct_keys": ["salaryLabel", "salary", "salaryRange", "compensation"],
        "dict_sub_keys": ["label", "display", "description", "text"],
    },
    "location": {
        "direct_keys": ["location", "jobLocation", "suburb", "area"],
        "dict_sub_keys": ["label", "description", "name", "display"],
        "handle_list": True,
    },
    "work_type": {
        "direct_keys": ["workType", "jobType", "employmentType"],
        "dict_sub_keys": ["label", "description"],
    },
}


def _extract_field(item, spec):
    """
    通用字段提取器，根据 spec 配置从 job item dict 中提取字段值。
    支持：直接 key、dict 子 key、list 首元素、嵌套父 key、递归查找。
    """
    min_len = spec.get("min_len", 1)
    coerce_str = spec.get("coerce_str", False)
    dict_sub_keys = spec.get("dict_sub_keys", [])
    handle_list = spec.get("handle_list", False)

    # Phase 1: 直接 key 查找
    for key in spec.get("direct_keys", []):
        val = item.get(key)
        if val is None:
            continue
        if coerce_str and val:
            return str(val)
        if isinstance(val, str) and len(val.strip()) >= min_len:
            return val.strip()
        if isinstance(val, dict) and dict_sub_keys:
            for sub in dict_sub_keys:
                sv = val.get(sub)
                if sv and isinstance(sv, str):
                    return sv.strip()
        if handle_list and isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict):
                for sub in dict_sub_keys:
                    sv = first.get(sub)
                    if sv and isinstance(sv, str):
                        return sv.strip()
            elif isinstance(first, str):
                return first.strip()

    # Phase 2: 嵌套父 key 查找
    for parent_key in spec.get("parent_keys", []):
        parent = item.get(parent_key)
        if isinstance(parent, dict):
            for sub in spec.get("sub_keys", spec.get("direct_keys", [])):
                val = parent.get(sub)
                if val is None:
                    continue
                if coerce_str and val:
                    return str(val)
                if isinstance(val, str) and len(val.strip()) >= min_len:
                    return val.strip()

    # Phase 3: 递归查找（可选）
    if spec.get("recursive"):
        max_depth = spec.get("max_depth", 3)
        r_keys = spec.get("recursive_keys", spec.get("direct_keys", [])[:2])
        result = _recursive_find(item, r_keys, max_depth, min_len)
        if result:
            return result

    return ""


def _recursive_find(obj, keys, max_depth, min_len=1, depth=0):
    """在嵌套 dict 中递归查找指定 key"""
    if depth > max_depth or not isinstance(obj, dict):
        return None
    for key in keys:
        val = obj.get(key)
        if val and isinstance(val, str) and len(val.strip()) >= min_len:
            return val.strip()
    for v in obj.values():
        if isinstance(v, dict):
            result = _recursive_find(v, keys, max_depth, min_len, depth + 1)
            if result:
                return result
    return None


# ── 薄包装：保持调用方不变 ──

def _extract_title(item):
    return _extract_field(item, _FIELD_SPECS["title"])


def _extract_id(item):
    return _extract_field(item, _FIELD_SPECS["id"])


def _extract_company(item):
    return _extract_field(item, _FIELD_SPECS["company"])


def _extract_salary(item):
    return _extract_field(item, _FIELD_SPECS["salary"])


def _extract_location(item):
    return _extract_field(item, _FIELD_SPECS["location"])


def _extract_work_type(item):
    return _extract_field(item, _FIELD_SPECS["work_type"])


def _extract_snippet(item):
    """从 job item 中提取摘要/要点"""
    parts = []
    for key in ['teaser', 'abstract', 'summary', 'shortDescription']:
        val = item.get(key)
        if val and isinstance(val, str) and len(val.strip()) > 0:
            parts.append(val.strip())

    bullets = item.get('bulletPoints', []) or item.get('keyPoints', [])
    if isinstance(bullets, list) and bullets:
        parts.append(' | '.join(str(b) for b in bullets if b))

    return ' '.join(parts)


def _extract_classification(item):
    """从 job item 中提取分类"""
    cls_data = item.get('classification', {})
    if isinstance(cls_data, dict):
        cls_desc = cls_data.get('description', '')
        sub_cls = cls_data.get('subClassification', {})
        sub_desc = sub_cls.get('description', '') if isinstance(sub_cls, dict) else ''
        return f"{cls_desc} > {sub_desc}" if sub_desc else cls_desc
    if isinstance(cls_data, str):
        return cls_data
    return ''


# ─────────────────────────────────────
# HTML DOM 解析（补充或回退）
# ─────────────────────────────────────

def _parse_html_job_cards(soup, results_list, seen_ids, keyword):
    """
    从 HTML DOM 中解析 job card，用于 __NEXT_DATA__ 失败时的回退，
    或者用于补充 __NEXT_DATA__ 中缺失的 title。
    返回新增条数。
    """
    count = 0

    # 多种可能的 card 选择器
    card_selectors = [
        'article[data-testid="job-card"]',
        'article[data-card-type="JobCard"]',
        '[data-testid="job-card"]',
        'div[data-job-id]',
        'article[data-job-id]',
        'div[class*="job-card"]',
        'div[class*="jobCard"]',
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    for card in cards:
        # 提取 job ID
        job_id = card.get('data-job-id', '')
        if not job_id:
            link = card.find('a', href=re.compile(r'/job/\d+'))
            if link:
                m = re.search(r'/job/(\d+)', link['href'])
                if m:
                    job_id = m.group(1)
        if not job_id or job_id in seen_ids:
            continue

        # 提取标题
        title = ''
        title_selectors = [
            '[data-testid="job-card-title"]',
            '[data-testid*="title"]',
            'h3 a', 'h3', 'h2 a', 'h2',
            'a[href*="/job/"]',
        ]
        for sel in title_selectors:
            el = card.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if t and len(t) > 2 and len(t) < 200:
                    title = t
                    break

        # 提取公司
        company = ''
        company_selectors = [
            '[data-testid="company-name"]',
            '[data-testid*="company"]',
            'span[class*="company"]',
            'a[class*="company"]',
        ]
        for sel in company_selectors:
            el = card.select_one(sel)
            if el:
                company = el.get_text(strip=True)
                break

        # 提取地点
        location = ''
        loc_selectors = [
            '[data-testid="job-card-location"]',
            '[data-testid*="location"]',
            'span[class*="location"]',
        ]
        for sel in loc_selectors:
            el = card.select_one(sel)
            if el:
                location = el.get_text(strip=True)
                break

        # 提取薪资
        salary = ''
        salary_selectors = [
            '[data-testid="job-card-salary"]',
            '[data-testid*="salary"]',
            'span[class*="salary"]',
        ]
        for sel in salary_selectors:
            el = card.select_one(sel)
            if el:
                salary = el.get_text(strip=True)
                break

        # 提取摘要：去掉标题/公司/薪资/地点后剩余的 card 文本
        snippet = ''
        card_text = card.get_text(separator=' ', strip=True)
        for remove_str in [title, company, salary, location]:
            if remove_str:
                card_text = card_text.replace(remove_str, '', 1)
        card_text = card_text.strip()
        if len(card_text) > 10:
            snippet = card_text[:300]

        seen_ids.add(job_id)
        results_list.append({
            "title": title,
            "company": company,
            "salary": salary,
            "snippet": snippet,
            "url": f"https://hk.jobsdb.com/job/{job_id}",
            "job_id": job_id,
            "posted_date": "",
            "location": location,
            "job_type": "",
            "classification": "",
            "search_keyword": keyword,
        })
        count += 1

    return count


def _build_html_title_map(soup):
    """
    从 HTML 中构建 {job_id: title} 的映射。
    用于补充 __NEXT_DATA__ 中提取不到的 title。
    """
    title_map = {}

    # 策略1: 通过 job card 元素
    card_selectors = [
        'article[data-testid="job-card"]',
        'article[data-card-type="JobCard"]',
        '[data-testid="job-card"]',
        'div[data-job-id]',
        'article[data-job-id]',
        'div[class*="job-card"]',
        'div[class*="jobCard"]',
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    for card in cards:
        job_id = card.get('data-job-id', '')
        if not job_id:
            link = card.find('a', href=re.compile(r'/job/\d+'))
            if link:
                m = re.search(r'/job/(\d+)', link['href'])
                if m:
                    job_id = m.group(1)
        if not job_id:
            continue

        title_el = (
            card.select_one('[data-testid="job-card-title"]')
            or card.select_one('[data-testid*="title"]')
            or card.select_one('h3 a')
            or card.select_one('h3')
            or card.select_one('h2 a')
            or card.select_one('h2')
        )
        if title_el:
            title_text = title_el.get_text(strip=True)
            if title_text and len(title_text) > 2:
                title_map[job_id] = title_text

    # 策略2: 通过所有 /job/ID 链接
    if not title_map:
        for a_tag in soup.find_all('a', href=re.compile(r'/job/\d+')):
            m = re.search(r'/job/(\d+)', a_tag['href'])
            if m:
                jid = m.group(1)
                text = a_tag.get_text(strip=True)
                if text and len(text) > 2 and len(text) < 200 and jid not in title_map:
                    title_map[jid] = text

    return title_map


# ─────────────────────────────────────
# 从列表页提取岗位链接
# ─────────────────────────────────────

# ─────────────────────────────────────
# 第一层：扫描 JobsDB 搜索列表页
# ─────────────────────────────────────

def scan_jobsdb_listings(keyword: str, location: str = "Hong Kong",
                         max_pages: int = 6, classification: str = "",
                         sort_by: str = "date", start_page: int = 1) -> list:
    """
    【第一层：列表页扫描】
    解析 JobsDB 搜索结果页，提取岗位基础信息。
    不打开详情页。

    Args:
        keyword: 搜索关键词
        location: 搜索地点
        max_pages: 翻页数
        classification: JobsDB 行业分类（可选），如 "science-technology"、"banking"
                        填写后 URL 变为 /{slug}-jobs-in-{classification}
        sort_by: 排序方式，"date" = 按发布时间 (sortmode=ListedDate)，
                 "relevance" = 按相关度 (JobsDB 默认，不传 sortmode)
        start_page: 起始页码（默认 1，用于跨 run 去重后补充翻页）

    Returns:
        list of dicts
    """
    results = []
    seen_ids = set()
    _debug_printed = False

    # 将关键词转换为 JobsDB 分类路径格式（保留原始大小写）
    # "Java Developer" → "Java-Developer-jobs"
    slug = "-".join(keyword.split())
    if classification:
        base_path = f"https://hk.jobsdb.com/{slug}-jobs-in-{classification}"
    else:
        base_path = f"https://hk.jobsdb.com/{slug}-jobs"

    # 创建共享 context，翻页过程复用，减少 Cloudflare 挑战
    browser = _get_playwright_browser()
    ctx = browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="en-HK",
        viewport={"width": 1920, "height": 1080},
    )

    try:
     for page in range(start_page, start_page + max_pages):
        params_parts = []
        if page > 1:
            params_parts.append(f"page={page}")
        if sort_by == "date":
            params_parts.append("sortmode=ListedDate")

        if params_parts:
            search_url = f"{base_path}?{'&'.join(params_parts)}"
        else:
            search_url = base_path
        emit(f"   🌐 扫描 JobsDB [{keyword}] 第{page}/{max_pages}页...")

        try:
            html = _fetch_html(search_url, wait_ms=4000, context=ctx)
            if not html:
                emit(f"      ⚠️ 第{page}页获取失败，停止翻页")
                break

            soup = BeautifulSoup(html, 'lxml')
            page_count = 0
            page_start_idx = len(results)

            # ══════════════════════════════════════════════
            #  策略 1: __NEXT_DATA__（结构化 JSON）
            # ══════════════════════════════════════════════
            next_tag = soup.find('script', id='__NEXT_DATA__')
            if next_tag and next_tag.string:
                try:
                    data = json.loads(next_tag.string)
                    jobs_data = _find_jobs_array(data)

                    if jobs_data:
                        # ── DEBUG: 检查首条数据结构 ──
                        if not _debug_printed:
                            sample = jobs_data[0]
                            sample_title = _extract_title(sample)
                            if not sample_title:
                                emit(f"      ⚠️ __NEXT_DATA__ title 为空！")
                                emit(f"      DEBUG keys: {sorted(sample.keys())[:20]}")
                                for k, v in sample.items():
                                    if isinstance(v, dict):
                                        emit(f"      DEBUG item['{k}'] keys: {sorted(v.keys())[:10]}")
                                    elif isinstance(v, str) and len(v) > 2 and len(v) < 100:
                                        emit(f"      DEBUG item['{k}'] = '{v}'")
                            _debug_printed = True

                        for item in jobs_data:
                            job_id = _extract_id(item)
                            if not job_id or job_id in seen_ids:
                                continue
                            seen_ids.add(job_id)

                            results.append({
                                "title": _extract_title(item),
                                "company": _extract_company(item),
                                "salary": _extract_salary(item),
                                "snippet": _extract_snippet(item),
                                "url": f"https://hk.jobsdb.com/job/{job_id}",
                                "job_id": job_id,
                                "posted_date": (
                                    item.get('listingDate', '')
                                    or item.get('postedDate', '')
                                    or item.get('listedAt', '')
                                ),
                                "location": _extract_location(item),
                                "job_type": _extract_work_type(item),
                                "classification": _extract_classification(item),
                                "search_keyword": keyword,
                            })
                            page_count += 1

                    if not jobs_data:
                        emit(f"      📭 第{page}页 __NEXT_DATA__ 中无 jobs 数组")

                except (json.JSONDecodeError, AttributeError) as e:
                    emit(f"      ⚠️ __NEXT_DATA__ 解析异常: {e}")

            # ══════════════════════════════════════════════
            #  策略 2: 当 __NEXT_DATA__ 有结果但 title 全为空时
            #          → 从 HTML DOM 中补充 title
            # ══════════════════════════════════════════════
            if page_count > 0:
                new_items = results[page_start_idx:]
                empty_count = sum(1 for r in new_items if not r.get('title', '').strip())
                if empty_count > page_count * 0.5:
                    emit(f"      ⚠️ {empty_count}/{page_count} 条 title 为空，从 HTML 补充...")
                    html_title_map = _build_html_title_map(soup)
                    if html_title_map:
                        updated = 0
                        for item in new_items:
                            if not item.get('title', '').strip():
                                jid = item.get('job_id', '')
                                if jid in html_title_map:
                                    item['title'] = html_title_map[jid]
                                    updated += 1
                        emit(f"      ✓ 从 HTML 补充了 {updated}/{empty_count} 条标题")
                    else:
                        emit(f"      ⚠️ HTML 中也未找到标题")

            # ══════════════════════════════════════════════
            #  策略 3: __NEXT_DATA__ 完全无结果时，纯 HTML 解析
            # ══════════════════════════════════════════════
            if page_count == 0:
                emit(f"      📋 尝试 HTML card 解析...")
                page_count = _parse_html_job_cards(soup, results, seen_ids, keyword)

            # ══════════════════════════════════════════════
            #  策略 4: 最后的回退 — 从 <a> 标签提取链接
            # ══════════════════════════════════════════════
            if page_count == 0:
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    full_url = href if href.startswith('http') else f"https://hk.jobsdb.com{href}"
                    if is_job_detail_url(full_url):
                        job_id_match = re.search(r'/job/(\d+)', full_url)
                        if job_id_match:
                            jid = job_id_match.group(1)
                            if jid not in seen_ids:
                                seen_ids.add(jid)
                                link_text = a_tag.get_text(strip=True) or ""
                                # 过滤掉太短或明显不是标题的文本
                                if len(link_text) < 3 or len(link_text) > 200:
                                    link_text = ""
                                results.append({
                                    "title": link_text,
                                    "company": "",
                                    "salary": "",
                                    "snippet": "",
                                    "url": f"https://hk.jobsdb.com/job/{jid}",
                                    "job_id": jid,
                                    "posted_date": "",
                                    "location": "",
                                    "job_type": "",
                                    "classification": "",
                                    "search_keyword": keyword,
                                })
                                page_count += 1

            emit(f"      ✓ 本页新增 {page_count} 条（累计 {len(results)}）")

            if page_count == 0:
                break

            time.sleep(random.uniform(1.5, 3.0))

        except Exception as e:
            emit(f"      ⚠️ 第{page}页异常: {e}")
            continue

    finally:
        try:
            ctx.close()
        except Exception:
            pass

    # ── 最终统计 ──
    total = len(results)
    with_title = sum(1 for r in results if r.get('title', '').strip())
    emit(f"   ✅ [{keyword}] 扫描完成，共 {total} 条（有标题: {with_title}）")

    if total > 0 and with_title == 0:
        emit(f"   ⚠️⚠️⚠️ 警告: 所有 {total} 条岗位的 title 均为空！")
        emit(f"   这通常意味着 JobsDB 页面结构已更新，需要更新选择器。")
        emit(f"   请将上方 DEBUG 输出的 keys 信息反馈给开发者。")

    return results


# ─────────────────────────────────────
# 兼容旧接口
# ─────────────────────────────────────

# ─────────────────────────────────────
# 抓取单个岗位详情
# ─────────────────────────────────────

def fetch_job_detail(url: str, context=None) -> dict:
    result = {
        'url': url,
        'title': '',
        'company': '',
        'location': '',
        'salary': '',
        'description': '',
        'requirements': '',
        'error': None,
    }

    try:
        html = _fetch_html(url, context=context)
        if not html:
            result['error'] = "无法获取页面内容 (requests + Playwright 均失败)"
            return result

        soup = BeautifulSoup(html, 'lxml')

        # ── 策略1: __NEXT_DATA__ ──
        next_tag = soup.find('script', id='__NEXT_DATA__')
        if next_tag and next_tag.string:
            try:
                data = json.loads(next_tag.string)
                info = _parse_next_data_detail(data)
                if info.get('title'):
                    result.update(info)
                    return result
            except (json.JSONDecodeError, KeyError):
                pass

        # ── 策略2: JSON-LD ──
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                ld = json.loads(tag.string)
                if isinstance(ld, list):
                    ld = next((x for x in ld if x.get('@type') == 'JobPosting'), None)
                if ld and ld.get('@type') == 'JobPosting':
                    result['title'] = ld.get('title', '')
                    org = ld.get('hiringOrganization', {})
                    result['company'] = org.get('name', '') if isinstance(org, dict) else str(org)
                    loc = ld.get('jobLocation', {})
                    if isinstance(loc, dict):
                        addr = loc.get('address', {})
                        result['location'] = addr.get('addressLocality', '') if isinstance(addr, dict) else str(addr)
                    desc = ld.get('description', '')
                    if desc and '<' in desc:
                        desc = BeautifulSoup(desc, 'lxml').get_text(separator='\n', strip=True)
                    result['description'] = desc
                    salary = ld.get('baseSalary', '')
                    if isinstance(salary, dict):
                        val = salary.get('value', {})
                        if isinstance(val, dict):
                            salary = f"{val.get('minValue', '')} - {val.get('maxValue', '')} {val.get('unitText', '')}"
                        else:
                            salary = str(val)
                    result['salary'] = str(salary)
                    if result['title']:
                        return result
            except (json.JSONDecodeError, AttributeError, StopIteration):
                continue

        # ── 策略3: HTML 直接解析 ──
        h1 = soup.find('h1')
        if h1:
            result['title'] = h1.get_text(strip=True)

        desc_selectors = [
            '[data-automation="jobDescription"]',
            '[data-automation="jobAdDetails"]',
            '[class*="jobDescription"]',
            '[class*="job-description"]',
            '#job-description',
            '.job-detail__body',
            'article',
        ]
        for sel in desc_selectors:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 100:
                result['description'] = el.get_text(separator='\n', strip=True)
                break

        if not result['description']:
            main = soup.find('main')
            if main:
                result['description'] = main.get_text(separator='\n', strip=True)[:5000]

        return result

    except Exception as e:
        result['error'] = f"解析失败: {e}"
        return result


def _parse_next_data_detail(data: dict) -> dict:
    """从岗位详情页的 __NEXT_DATA__ 中提取信息"""
    info = {}
    try:
        props = data.get('props', {}).get('pageProps', {})
        # 尝试多种路径找到 job 对象
        job = None
        for key in ['jobDetail', 'job', 'jobData', 'data']:
            candidate = props.get(key)
            if isinstance(candidate, dict):
                job = candidate
                break
        if not job:
            job = props

        info['title'] = _extract_title(job)
        info['company'] = _extract_company(job)
        info['location'] = _extract_location(job)
        info['salary'] = _extract_salary(job)

        desc = ''
        for key in ['description', 'jobDescription', 'content', 'jobContent']:
            val = job.get(key)
            if val and isinstance(val, str) and len(val) > 50:
                desc = val
                break
            if isinstance(val, dict):
                for sub in ['text', 'html', 'content']:
                    sv = val.get(sub)
                    if sv and isinstance(sv, str) and len(sv) > 50:
                        desc = sv
                        break
                if desc:
                    break

        if desc and '<' in desc:
            desc = BeautifulSoup(desc, 'lxml').get_text(separator='\n', strip=True)
        info['description'] = desc

    except Exception as e:
        emit(f"   ⚠️ __NEXT_DATA__ 详情解析异常: {e}")
    return info


# ─────────────────────────────────────
# 批量抓取
# ─────────────────────────────────────

def fetch_multiple_details(urls: list, delay: float = 2.0, max_jobs: int = 20) -> list:
    results = []
    total = min(len(urls), max_jobs)

    PAGE_LIMIT = 25  # 每个 context 最多复用 25 页，超限重建以防 Cloudflare 重新挑战
    ctx = None
    ctx_pages = 0

    def _ensure_context():
        """获取或重建 browser context。首次创建，超限或失效时重建。"""
        nonlocal ctx, ctx_pages
        if ctx is None or ctx_pages >= PAGE_LIMIT:
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
            browser = _get_playwright_browser()
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="en-HK",
                viewport={"width": 1920, "height": 1080},
            )
            ctx_pages = 0
            emit(f"   🌐 已创建新 browser context（每 {PAGE_LIMIT} 页轮换）")

    try:
        for i, url in enumerate(urls[:max_jobs]):
            _ensure_context()
            emit(f"   📄 抓取 JD {i+1}/{total}: {url[:70]}...")
            detail = fetch_job_detail(url, context=ctx)
            if detail.get('error'):
                emit(f"      ⚠️ {detail['error']}")
                # 复用 context 时出错：context 可能已被 _fetch_html 关闭，强制下次重建
                ctx_pages = PAGE_LIMIT
            else:
                desc_len = len(detail.get('description', ''))
                emit(f"      ✓ {detail.get('title', '?')[:40]} | JD长度: {desc_len}字")
                ctx_pages += 1
            results.append(detail)

            if i < total - 1:
                time.sleep(random.uniform(delay, delay + 2.0))

    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass

    success = sum(1 for r in results if r.get('description') and not r.get('error'))
    emit(f"   ✅ 抓取完成: {success}/{total} 成功获取完整 JD")
    return results