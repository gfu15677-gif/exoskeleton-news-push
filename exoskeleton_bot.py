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

# 搜索关键词列表（去掉年份限制，扩大覆盖面）
SEARCH_QUERIES = [
    # 中文 - 综合
    "外骨骼 最新资讯",
    "外骨骼机器人 新闻",
    "外骨骼 行业动态",
    # 中文 - 科研
    "外骨骼 研究进展",
    "外骨骼 科研成果 论文",
    # 中文 - 公司/产品
    "外骨骼 融资 产品",
    "外骨骼机器人 公司 发布",
    # 中文 - 视频
    "外骨骼 bilibili",
    "外骨骼 视频",
    # 英文 - 综合
    "exoskeleton news",
    "exoskeleton robot latest",
    # 英文 - 科研
    "exoskeleton research breakthrough",
    # 英文 - 公司
    "exoskeleton company funding launch",
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


def _clean_html(text: str) -> str:
    """清理HTML标签和实体"""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def search_duckduckgo(query: str) -> list:
    """使用DuckDuckGo搜索获取结果"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # DuckDuckGo HTML结果解析 - 多种正则兼容
        patterns = [
            r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?(?:result__snippet|result__url)[^>]*>(.*?)</(?:a|span)>',
        ]

        result_blocks = []
        for pattern in patterns:
            blocks = re.findall(pattern, html, re.DOTALL)
            if blocks:
                result_blocks = blocks
                break

        for href, title, snippet in result_blocks[:8]:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://duckduckgo.com" + href

            title = _clean_html(title)
            snippet = _clean_html(snippet)

            if title and href and "duckduckgo.com" not in href:
                results.append({"title": title, "url": href, "snippet": snippet})

    except Exception as e:
        print(f"  DuckDuckGo搜索异常: {e}")

    return results


def search_bing(query: str) -> list:
    """使用Bing搜索获取结果"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.bing.com/search?q={encoded_query}&count=10"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Bing搜索结果解析 - 多种正则兼容
        patterns = [
            r'<li class="b_algo"[^>]*>.*?<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>.*?<p[^>]*>(.*?)</p>',
            r'<li class="b_algo"[^>]*>.*?<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>.*?<div[^>]*>(.*?)</div>',
            r'<li class="b_algo"[^>]*>.*?<a href="([^"]+)"[^>]*><h2>(.*?)</h2></a>.*?<p[^>]*>(.*?)</p>',
        ]

        result_blocks = []
        for pattern in patterns:
            blocks = re.findall(pattern, html, re.DOTALL)
            if blocks:
                result_blocks = blocks
                break

        for href, title, snippet in result_blocks[:8]:
            title = _clean_html(title)
            snippet = _clean_html(snippet)

            if title and href:
                results.append({"title": title, "url": href, "snippet": snippet})

    except Exception as e:
        print(f"  Bing搜索异常: {e}")

    return results


def search_google(query: str) -> list:
    """使用Google搜索获取结果（第三备用）"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}&num=10&hl=zh-CN"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Google搜索结果解析
        patterns = [
            r'<a href="/url\?q=([^&"]+)&[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>.*?</a>.*?<div[^>]*>(.*?)</div>',
            r'<div class="BNeawe s3v9rd AP7Wnd">(.*?)</div>.*?<div class="BNeawe vvjwJb AP7Wnd">(.*?)</div>.*?<a href="([^"]+)"',
        ]

        result_blocks = []
        for pattern in patterns:
            blocks = re.findall(pattern, html, re.DOTALL)
            if blocks:
                result_blocks = blocks
                break

        for match in result_blocks[:8]:
            if len(match) == 3:
                href, title, snippet = match
            else:
                continue

            title = _clean_html(title)
            snippet = _clean_html(snippet)

            # 过滤Google内部链接
            if title and href and "google.com" not in href and "webcache" not in href:
                results.append({"title": title, "url": href, "snippet": snippet})

    except Exception as e:
        print(f"  Google搜索异常: {e}")

    return results


def search_web(query: str) -> list:
    """
    搜索资讯，依次尝试 DuckDuckGo → Bing → Google
    返回格式: [{"title": "", "url": "", "snippet": ""}, ...]
    """
    # 第一选择：DuckDuckGo
    results = search_duckduckgo(query)
    if results:
        print(f"    DuckDuckGo: {len(results)}条")
        return results

    # 第二选择：Bing
    print(f"  DuckDuckGo无结果，尝试Bing...")
    results = search_bing(query)
    if results:
        print(f"    Bing: {len(results)}条")
        return results

    # 第三选择：Google
    print(f"  Bing也无结果，尝试Google...")
    results = search_google(query)
    if results:
        print(f"    Google: {len(results)}条")
        return results

    print(f"  所有搜索引擎均无结果")
    return []


def categorize_item(title: str, snippet: str) -> str:
    """根据标题和内容分类"""
    text = (title + " " + snippet).lower()

    # 视频类
    if any(kw in text for kw in ["bilibili", "哔哩哔哩", "b站", "抖音", "视频", "video", "youtube", "youku", "优酷"]):
        return "video"

    # 科研类
    if any(kw in text for kw in ["研究", "科研", "论文", "学术", "patent", "research", "study", "breakthrough", "中科院", "研究所", "university", "期刊", "nature", "science", "ieee", "robotics"]):
        return "research"

    # 公司动态（融资/产品）
    if any(kw in text for kw in ["融资", "投资", "轮", "产品", "发布", "launch", "funding", "investment", "series", "million", "billion", "product", "首发", "上市", "获投"]):
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

    # 搜索全部关键词（不再随机抽样）
    for query in SEARCH_QUERIES:
        print(f"  搜索: {query}")
        results = search_web(query)
        for r in results:
            r["category"] = categorize_item(r["title"], r.get("snippet", ""))
        all_results.extend(results)
        time.sleep(random.uniform(0.5, 2))  # 避免请求过快

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

    # 企业微信文本消息限制2048字符，超长则截断
    if len(content) > 2000:
        content = content[:1990] + "\n...更多内容下期见"
        print("消息过长，已截断")

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
