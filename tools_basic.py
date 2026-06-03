"""
tools_basic.py - 基础工具函数（时间、文件、搜索、配置查看、岗位详情）
"""
import os
import json
from datetime import datetime
from ddgs import DDGS

from config import (
    emit, OUTPUT_DIR, track_file,
    load_profile, load_search_config_dict,
    get_current_run_dir, get_latest_run_dir,
)
from scraper import fetch_job_detail as scraper_fetch_detail


def get_current_time():
    """获取当前日期和时间"""
    now = datetime.now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return now.strftime("%Y年%m月%d日 %H:%M:%S 星期") + weekdays[now.weekday()]


def write_file(filename, content):
    """写入文件到 output 目录"""
    filepath = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    track_file(filepath, f"用户文件: {filename}")
    return f"文件已创建: {os.path.abspath(filepath)}"


def read_file(filename):
    """读取 output 目录中的文件"""
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return f"错误：文件 {filename} 不存在"
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def list_files():
    """列出当前 run 目录（或最近 run）中的文件，以及 market 目录"""
    run_dir = get_current_run_dir() or get_latest_run_dir()
    lines = []

    if run_dir and os.path.exists(run_dir):
        run_name = os.path.basename(run_dir)
        lines.append(f"📂 当前 Run: {run_name}/")
        for root, dirs, files in os.walk(run_dir):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), run_dir)
                lines.append(f"  📄 {rel}")

    market_dir = os.path.join(OUTPUT_DIR, "market")
    if os.path.exists(market_dir):
        market_files = []
        for root, dirs, files in os.walk(market_dir):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), OUTPUT_DIR)
                market_files.append(rel)
        if market_files:
            lines.append(f"\n📂 市场分析:")
            for f in sorted(market_files):
                lines.append(f"  📄 {f}")

    if not lines:
        return "output 文件夹是空的"
    return "当前文件列表：\n" + "\n".join(lines)


def web_search(query, max_results=5):
    """DuckDuckGo 联网搜索"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="wt-wt", max_results=max_results))
        if not results:
            return "没有搜索到相关结果"
        output = f"搜索「{query}」的结果：\n\n"
        for i, r in enumerate(results, 1):
            output += f"{i}. **{r['title']}**\n"
            output += f"   {r['body']}\n"
            output += f"   链接：{r['href']}\n\n"
        return output
    except Exception as e:
        return f"搜索出错：{str(e)}"


def load_user_profile():
    """读取用户个人档案 profiles/me.yaml（面向 LLM 的格式化输出）"""
    profile, err = load_profile()
    if err:
        return err
    return "✅ 用户档案已加载：\n" + json.dumps(profile, ensure_ascii=False, indent=2)


def load_search_config():
    """读取搜索策略配置 profiles/search_config.yaml（面向 LLM 的格式化输出）"""
    config, err = load_search_config_dict()
    if err:
        return err
    return "✅ 搜索配置已加载：\n" + json.dumps(config, ensure_ascii=False, indent=2)


def fetch_job_detail(url):
    """抓取单个岗位 URL 的完整 JD"""
    emit(f"   📄 抓取: {url[:70]}...")
    detail = scraper_fetch_detail(url)
    if detail.get("error"):
        return f"❌ 抓取失败: {detail['error']}"
    output = f"✅ 岗位详情：\n"
    output += f"   标题: {detail.get('title', '未知')}\n"
    output += f"   公司: {detail.get('company', '未知')}\n"
    output += f"   地点: {detail.get('location', '未知')}\n"
    output += f"   薪资: {detail.get('salary', '未标明')}\n"
    output += f"   JD 长度: {len(detail.get('description', ''))} 字\n\n"
    output += f"--- 完整职位描述 ---\n{detail.get('description', '无内容')}\n"
    return output
