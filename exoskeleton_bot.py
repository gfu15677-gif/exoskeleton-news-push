#!/usr/bin/env python3
"""
外骨骼资讯自动推送脚本 v3
核心改动：弃用搜索引擎HTML正则解析，改用RSS订阅源 + 新闻API
RSS返回标准XML，解析100%稳定
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
import xml.etree.ElementTree as ET

# ============ 配置 ============
WEBHOOK_KEY = os.environ.get("WECHAT_WEBHOOK_KEY", "")
WEBHOOK_URL = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY}"

CST = timezone(timedelta(hours=8))

# ============ 通用工具 ============

def http_get(url, headers=None, timeout=20):
    """通用HTTP GET请求"""
    if headers is None:
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean_html(text):
    """清理HTML标签和实体"""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_date_flexible(date_str):
    """灵活解析多种日期格式"""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def is_recent(pub_date_str, days=7):
    """判断发布日期是否在最近N天内"""
    pub_date = parse_date_flexible(pub_date_str)
    if pub_date is None:
        return True
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=CST)
    now = datetime.now(CST)
    return (now - pub_date).days <= days


def format_date_display(pub_date_str):
    """将发布日期格式化为简短显示"""
    pub_date = parse_date_flexible(pub_date_str)
    if pub_date is None:
        return ""
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=CST)
    now = datetime.now(CST)
    delta = now - pub_date
    if delta.days == 0:
        return "今天"
    elif delta.days == 1:
        return "昨天"
    elif delta.days <= 7:
        return f"{delta.days}天前"
    else:
        return pub_date.strftime("%m/%d")


# ============ 数据源1: Google News RSS（主力） ============

def search_google_news_rss(query, max_results=10):
    """
    Google News RSS 搜索
    Google官方RSS端点，返回标准XML，极其稳定
    """
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

        data = http_get(url)
        root = ET.fromstring(data)

        items = root.findall(".//item")
        for item in items[:max_results]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pubdate_elem = item.find("pubDate")
            source_elem = item.find("{http://purl.org/dc/elements/1.1/}source")

            title = clean_html(title_elem.text) if title_elem is not None and title_elem.text else ""
            link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            desc = clean_html(desc_elem.text) if desc_elem is not None and desc_elem.text else ""
            pub_date = pubdate_elem.text if pubdate_elem is not None and pubdate_elem.text else ""
            source_name = source_elem.text if source_elem is not None and source_elem.text else ""

            # 从description中提取来源信息（Google News RSS的title格式为"标题 - 来源"）
            if " - " in title and not source_name:
                parts = title.rsplit(" - ", 1)
                if len(parts) == 2:
                    title = parts[0].strip()
                    source_name = parts[1].strip()

            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": desc[:200] if desc else "",
                    "pub_date": pub_date,
                    "source": source_name or "Google News",
                })

        print(f"    Google News RSS: {len(results)}条")

    except Exception as e:
        print(f"    Google News RSS异常: {e}")

    return results


# ============ 数据源2: Bing News RSS ============

def search_bing_news_rss(query, max_results=10):
    """
    Bing News RSS 搜索
    Bing也有RSS端点，链接更干净
    """
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/news/search?q={encoded}&format=rss"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        data = http_get(url, headers=headers)
        root = ET.fromstring(data)

        items = root.findall(".//item")
        for item in items[:max_results]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pubdate_elem = item.find("pubDate")

            title = clean_html(title_elem.text) if title_elem is not None and title_elem.text else ""
            link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            desc = clean_html(desc_elem.text) if desc_elem is not None and desc_elem.text else ""
            pub_date = pubdate_elem.text if pubdate_elem is not None and pubdate_elem.text else ""

            # Bing RSS的title格式也经常是"标题 - 来源"
            source_name = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                if len(parts) == 2:
                    title = parts[0].strip()
                    source_name = parts[1].strip()

            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": desc[:200] if desc else "",
                    "pub_date": pub_date,
                    "source": source_name or "Bing News",
                })

        print(f"    Bing News RSS: {len(results)}条")

    except Exception as e:
        print(f"    Bing News RSS异常: {e}")

    return results


# ============ 数据源3: DuckDuckGo Instant Answer API ============

def search_duckduckgo_api(query, max_results=8):
    """
    DuckDuckGo Instant Answer API
    返回JSON，不是HTML，解析稳定
    """
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"

        data = http_get(url)
        resp = json.loads(data.decode("utf-8"))

        # 相关主题
        for topic in resp.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and "Text" in topic and "FirstURL" in topic:
                text = topic["Text"]
                results.append({
                    "title": text[:80] if len(text) > 80 else text,
                    "url": topic["FirstURL"],
                    "snippet": text[:200],
                    "pub_date": "",
                    "source": "DuckDuckGo",
                })

        # 直接回答
        abstract = resp.get("Abstract", "")
        abstract_url = resp.get("AbstractURL", "")
        if abstract and abstract_url:
            results.insert(0, {
                "title": resp.get("AbstractTitle", abstract[:80]),
                "url": abstract_url,
                "snippet": abstract[:200],
                "pub_date": "",
                "source": "DuckDuckGo",
            })

        print(f"    DuckDuckGo API: {len(results)}条")

    except Exception as e:
        print(f"    DuckDuckGo API异常: {e}")

    return results


# ============ 统一搜索入口 ============

def search_all():
    """使用RSS/API数据源搜索外骨骼资讯"""
    all_results = []

    # 精简搜索关键词（RSS/News搜索自带相关性排序，不需要修饰词）
    search_queries = [
        "外骨骼",
        "外骨骼机器人",
        "exoskeleton",
        "exoskeleton robot",
    ]

    # 数据源1: Google News RSS（主力）
    print("\n📡 数据源1: Google News RSS")
    for query in search_queries:
        print(f"  搜索: {query}")
        results = search_google_news_rss(query)
        all_results.extend(results)
        time.sleep(random.uniform(0.3, 1.0))

    # 数据源2: Bing News RSS（补充）
    print("\n📡 数据源2: Bing News RSS")
    for query in search_queries[:2]:
        print(f"  搜索: {query}")
        results = search_bing_news_rss(query)
        all_results.extend(results)
        time.sleep(random.uniform(0.3, 1.0))

    # 数据源3: DuckDuckGo API（兜底）
    if len(all_results) < 5:
        print("\n📡 数据源3: DuckDuckGo API（兜底）")
        for query in search_queries[:2]:
            print(f"  搜索: {query}")
            results = search_duckduckgo_api(query)
            all_results.extend(results)
            time.sleep(random.uniform(0.3, 1.0))

    return all_results


# ============ 分类 ============

def categorize_item(title, snippet):
    """根据标题和内容分类"""
    text = (title + " " + snippet).lower()

    if any(kw in text for kw in ["bilibili", "哔哩哔哩", "b站", "抖音", "视频", "video", "youtube", "youku"]):
        return "video"

    if any(kw in text for kw in ["研究", "科研", "论文", "学术", "patent", "research", "study", "breakthrough", "中科院", "研究所", "university", "期刊", "nature", "science", "ieee", "journal"]):
        return "research"

    if any(kw in text for kw in ["融资", "投资", "轮", "产品", "发布", "launch", "funding", "investment", "series", "million", "billion", "product", "首发", "上市", "获投", "startup"]):
        return "company"

    return "news"


# ============ 去重 ============

def deduplicate(results):
    """按URL和标题去重"""
    seen_urls = set()
    seen_titles = set()
    unique = []

    for r in results:
        url = r.get("url", "")
        title = r.get("title", "").strip()

        if url in seen_urls:
            continue

        # 标题去重（去掉标点和空格后比较）
        title_simple = re.sub(r'[^\w\u4e00-\u9fff]', '', title).lower()
        if title_simple and title_simple in seen_titles:
            continue

        seen_urls.add(url)
        if title_simple:
            seen_titles.add(title_simple)

        unique.append(r)

    return unique


# ============ 时效性过滤 ============

def filter_recent(results, days=7):
    """只保留最近N天的结果"""
    recent = []
    for r in results:
        if is_recent(r.get("pub_date", ""), days):
            recent.append(r)
    return recent


# ============ 构建推送消息 ============

def build_push_content(all_results, push_index):
    """构建推送消息内容"""
    now = datetime.now(CST)
    date_str = now.strftime("%m月%d日")

    videos = [r for r in all_results if r["category"] == "video"]
    research = [r for r in all_results if r["category"] == "research"]
    company = [r for r in all_results if r["category"] == "company"]
    news_list = [r for r in all_results if r["category"] == "news"]

    lines = []
    lines.append(f"🤖 外骨骼日报 | {date_str} · 第{push_index}期")
    lines.append("")

    def add_section(emoji, section_name, items, max_count=3):
        if not items:
            return
        lines.append(f"{emoji} {section_name}")
        for i, item in enumerate(items[:max_count], 1):
            source = item.get("source", "")
            date_display = format_date_display(item.get("pub_date", ""))
            meta_parts = []
            if source and source not in ("Google News", "Bing News"):
                meta_parts.append(source)
            if date_display:
                meta_parts.append(date_display)
            meta = f"（{' · '.join(meta_parts)}）" if meta_parts else ""

            lines.append(f"{i}. {item['title']}{meta}")
            lines.append(f"🔗 {item['url']}")
            if item.get("snippet"):
                snippet = item['snippet'][:80]
                lines.append(f"   {snippet}...")
        lines.append("")

    add_section("🎬", "视频推荐", videos)
    add_section("🔬", "科研进展", research)
    add_section("📰", "行业资讯", news_list)
    add_section("💰", "公司动态", company)

    if not any([videos, research, company, news_list]):
        lines.append("今天暂时没找到新的外骨骼资讯，下次再看看 👀")

    return "\n".join(lines)


# ============ 企业微信推送 ============

def send_text_to_wechat(content):
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


# ============ 主流程 ============

def main():
    print("=" * 50)
    print("外骨骼资讯推送脚本 v3 启动")
    print(f"时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if not WEBHOOK_KEY:
        print("错误: 环境变量 WECHAT_WEBHOOK_KEY 未设置")
        sys.exit(1)

    # 确定推送期数
    hour = datetime.now(CST).hour
    if 6 <= hour < 12:
        push_index = 1
    elif 12 <= hour < 18:
        push_index = 2
    else:
        push_index = 3

    print(f"当前推送: 第{push_index}期")

    # 搜索
    print("\n开始搜索（RSS/API数据源）...")
    all_results = search_all()

    # 去重
    unique_results = deduplicate(all_results)
    print(f"\n去重后: {len(unique_results)} 条")

    # 时效性过滤（7天内）
    recent_results = filter_recent(unique_results, days=7)
    print(f"7天内: {len(recent_results)} 条")

    # 分类
    for r in recent_results:
        r["category"] = categorize_item(r["title"], r.get("snippet", ""))

    # 排序：视频 > 科研 > 资讯 > 公司
    category_order = {"video": 0, "research": 1, "news": 2, "company": 3}
    recent_results.sort(key=lambda x: category_order.get(x["category"], 99))

    print(f"最终推送: {len(recent_results)} 条")

    # 构建消息
    content = build_push_content(recent_results, push_index)

    print("\n推送内容预览:")
    print("-" * 50)
    preview = content[:800] + "..." if len(content) > 800 else content
    print(preview)
    print("-" * 50)

    # 企业微信文本消息限制2048字符
    if len(content) > 2000:
        content = content[:1990] + "\n...更多内容下期见"
        print("消息过长，已截断")

    # 发送
    print("\n正在推送到企业微信群...")
    success = send_text_to_wechat(content)

    if success:
        print("✅ 推送完成")
    else:
        print("❌ 推送失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
