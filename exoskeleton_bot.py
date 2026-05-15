#!/usr/bin/env python3
"""
外骨骼资讯自动推送脚本
功能：搜索外骨骼相关资讯，整理格式，推送到企业微信群
触发方式：定时运行（每天9:00/15:00/21:00）
"""

import os
import sys
import json
import time
import random
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from html import unescape
import re

# ============ 配置 ============
WEBHOOK_KEY = os.environ.get("WECHAT_WEBHOOK_KEY", "")
WEBHOOK_URL = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY}"

# 搜索关键词列表
SEARCH_QUERIES = [
    "外骨骼 最新研究 科研成果 2025 2026",
    "exoskeleton latest research breakthrough 2025 2026",
    "外骨骼机器人 公司 融资 产品发布 2025 2026",
    "exoskeleton company funding product launch 2025 2026",
    "外骨骼 bilibili 视频 2025 2026",
    "外骨骼 抖音 视频 最新",
    "外骨骼 行业资讯 新闻 政策 2025 2026",
]

# ============ 工具函数 ============

def send_text_to_wechat(content: str) -> bool:
    """发送文本消息到企业微信群"""
    if not WEBHOOK_KEY:
        print("错误: 未设置 WECHAT_WEBHOOK_KEY 环境变量")
        return False

    payload = {
        "msgtype": "text",
        "text": {"content": content}
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}

    req = urllib.request.Request(WEBHOOK_URL, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode") == 0:
                print("消息发送成功")
                return True
            else:
                print(f"发送失败: {result}")
                return False
    except Exception as e:
        print(f"发送异常: {e}")
        return False


def send_markdown_to_wechat(content: str) -> bool:
    """发送Markdown消息到企业微信群"""
    if not WEBHOOK_KEY:
        print("错误: 未设置 WECHAT_WEBHOOK_KEY 环境变量")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content}
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}

    req = urllib.request.Request(WEBHOOK_URL, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode") == 0:
                print("Markdown消息发送成功")
                return True
            else:
                print(f"发送失败: {result}")
                return False
    except Exception as e:
        print(f"发送异常: {e}")
        return False


def search_duckduckgo(query: str) -> list:
    """使用DuckDuckGo搜索获取结果"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        result_blocks = re.findall(
            r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>.*?<a class="result__snippet">(.*?)</a>',
            html,
            re.DOTALL
        )

        for href, title, snippet in result_blocks[:5]:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://duckduckgo.com" + href

            title = unescape(re.sub(r'<[^>]+>', '', title)).strip()
            snippet = unescape(re.sub(r'<[^>]+>', '', snippet)).strip()

            if title and href and "duckduckgo.com" not in href:
                results.append({"title": title, "url": href, "snippet": snippet})

    except Exception as e:
        print(f"  DuckDuckGo搜索异常: {e}")

    return results


def search_bing(query: str) -> list:
    """使用Bing搜索获取结果（备用）"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.bing.com/search?q={encoded_query}&count=5"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Bing搜索结果解析
        result_blocks = re.findall(
            r'<li class="b_algo"[^>]*>.*?<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>.*?<p>(.*?)</p>.*?</li>',
            html,
            re.DOTALL
        )

        for href, title, snippet in result_blocks[:5]:
            title = unescape(re.sub(r'<[^>]+>', '', title)).strip()
            snippet = unescape(re.sub(r'<[^>]+>', '', snippet)).strip()

            if title and href:
                results.append({"title": title, "url": href, "snippet": snippet})

    except Exception as e:
        print(f"  Bing搜索异常: {e}")

    return results


def search_web(query: str) -> list:
    """
    搜索外骨骼相关资讯，优先DuckDuckGo，失败时回退到Bing
    返回格式: [{"title": "", "url": "", "snippet": ""}, ...]
    """
    results = search_duckduckgo(query)
    if not results:
        print(f"  DuckDuckGo无结果，尝试Bing...")
        results = search_bing(query)
    return results


def categorize_item(title: str, snippet: str) -> str:
    """根据标题和内容分类"""
    text = (title + " " + snippet).lower()

    # 视频类
    if any(kw in text for kw in ["bilibili", "哔哩哔哩", "b站", "抖音", "视频", "video", "youtube"]):
        return "video"

    # 科研类
    if any(kw in text for kw in ["研究", "科研", "论文", "学术", "patent", "research", "study", "breakthrough", "中科院", "研究所", "university"]):
        return "research"

    # 公司动态（融资/产品）
    if any(kw in text for kw in ["融资", "投资", "轮", "产品", "发布", "launch", "funding", "investment", "series", "million", "billion", "product"]):
        return "company"

    # 默认归为行业资讯
    return "news"


def build_push_content(all_results: list, push_index: int) -> str:
    """构建推送消息内容"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    date_str = now.strftime("%m月%d日")

    # 分类
    videos = [r for r in all_results if r["category"] == "video"]
    research = [r for r in all_results if r["category"] == "research"]
    company = [r for r in all_results if r["category"] == "company"]
    news = [r for r in all_results if r["category"] == "news"]

    lines = []
    lines.append(f"🤖 外骨骼日报 | {date_str} · 第{push_index}期")
    lines.append("")

    # 视频推荐
    if videos:
        lines.append("🎬 视频推荐")
        for i, item in enumerate(videos[:3], 1):
            lines.append(f"{i}. {item['title']}")
            lines.append(f"🔗 {item['url']}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet'][:60]}...")
            lines.append("")

    # 科研进展
    if research:
        lines.append("🔬 科研进展")
        for i, item in enumerate(research[:3], 1):
            lines.append(f"{i}. {item['title']}")
            lines.append(f"🔗 {item['url']}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet'][:60]}...")
            lines.append("")

    # 行业资讯
    if news:
        lines.append("📰 行业资讯")
        for i, item in enumerate(news[:3], 1):
            lines.append(f"{i}. {item['title']}")
            lines.append(f"🔗 {item['url']}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet'][:60]}...")
            lines.append("")

    # 公司动态
    if company:
        lines.append("💰 公司动态")
        for i, item in enumerate(company[:3], 1):
            lines.append(f"{i}. {item['title']}")
            lines.append(f"🔗 {item['url']}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet'][:60]}...")
            lines.append("")

    # 如果没有搜到任何内容
    if not any([videos, research, company, news]):
        lines.append("今天暂时没找到新的外骨骼资讯，下次再看看 👀")

    return "\n".join(lines)


# ============ 主流程 ============

def main():
    print("=" * 50)
    print("外骨骼资讯推送脚本启动")
    print(f"时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if not WEBHOOK_KEY:
        print("错误: 环境变量 WECHAT_WEBHOOK_KEY 未设置")
        sys.exit(1)

    # 确定推送期数
    hour = datetime.now(timezone(timedelta(hours=8))).hour
    if 6 <= hour < 12:
        push_index = 1
    elif 12 <= hour < 18:
        push_index = 2
    else:
        push_index = 3

    print(f"当前推送: 第{push_index}期")

    # 搜索资讯
    all_results = []
    print("\n开始搜索...")

    # 随机选3个关键词搜索，避免每次都一样
    selected_queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))

    for query in selected_queries:
        print(f"  搜索: {query}")
        results = search_web(query)
        for r in results:
            r["category"] = categorize_item(r["title"], r.get("snippet", ""))
        all_results.extend(results)
        time.sleep(random.uniform(1, 3))  # 避免请求过快

    # 去重（按URL）
    seen_urls = set()
    unique_results = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_results.append(r)

    print(f"\n共找到 {len(unique_results)} 条不重复结果")

    # 构建消息
    content = build_push_content(unique_results, push_index)

    print("\n推送内容预览:")
    print("-" * 50)
    print(content[:500] + "..." if len(content) > 500 else content)
    print("-" * 50)

    # 发送消息
    print("\n正在推送到企业微信群...")
    success = send_text_to_wechat(content)

    if success:
        print("✅ 推送完成")
    else:
        print("❌ 推送失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
