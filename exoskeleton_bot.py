#!/usr/bin/env python3
"""
外骨骼资讯自动推送脚本 v6
核心改动：跨次运行去重，同一条资讯只推送一次
数据源：天行数据新闻API(主力) + B站视频搜索 + 36氪RSS + InfoQ中文RSS + Solidot RSS
所有链接国内直连，无需翻墙
推送历史通过pushed_history.json持久化，配合GitHub Actions Cache跨次运行
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

# 天行数据API Key（注册https://www.tianapi.com获取，普通会员免费100次/天）
TIANAPI_KEY = os.environ.get("TIANAPI_KEY", "")

# B站Cookie（可选，用于搜索API防风控；不设置也能用但容易被412拦截）
BILIBILI_COOKIE = os.environ.get("BILIBILI_COOKIE", "")

CST = timezone(timedelta(hours=8))

# 时效性过滤天数
RECENT_DAYS = 3

# 推送历史文件路径（GitHub Actions通过Cache持久化此文件）
HISTORY_FILE = os.environ.get("PUSH_HISTORY_FILE", "pushed_history.json")

# 推送历史保留天数（超过此天数的记录自动清理）
HISTORY_RETAIN_DAYS = 7


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
    date_str = date_str.strip()
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def is_recent(pub_date_str, days=RECENT_DAYS):
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
        hours = delta.seconds // 3600
        if hours == 0:
            minutes = delta.seconds // 60
            return f"{minutes}分钟前" if minutes > 0 else "刚刚"
        return f"{hours}小时前"
    elif delta.days == 1:
        return "昨天"
    elif delta.days <= 7:
        return f"{delta.days}天前"
    else:
        return pub_date.strftime("%m/%d")


# ============ 数据源1: 天行数据新闻API（主力） ============

def _search_tianapi(endpoint, query, num=10, page=1):
    """
    天行数据新闻API通用搜索
    endpoint: guonei(国内新闻) / generalnews(综合新闻)
    支持关键词搜索(word参数)，链接为原始来源URL，国内直连
    免费会员100次/天
    """
    results = []
    try:
        params = {
            "key": TIANAPI_KEY,
            "word": query,
            "num": num,
            "page": page,
        }
        url = f"https://apis.tianapi.com/{endpoint}/index?" + urllib.parse.urlencode(params)

        data = http_get(url)
        resp = json.loads(data.decode("utf-8"))

        if resp.get("code") != 200:
            print(f"    天行数据({endpoint})返回: code={resp.get('code')}, msg={resp.get('msg')}")
            return results

        for item in resp.get("result", {}).get("newslist", []):
            title = item.get("title", "").strip()
            url_link = item.get("url", "").strip()
            description = item.get("description", "").strip()
            source = item.get("source", "").strip()
            pub_date = item.get("ctime", "").strip()

            if title:
                results.append({
                    "title": title,
                    "url": url_link,
                    "snippet": description[:200] if description else "",
                    "pub_date": pub_date,
                    "source": source,
                })

        print(f"    天行数据-{endpoint} ({query}): {len(results)}条")

    except Exception as e:
        print(f"    天行数据({endpoint})异常: {e}")

    return results


def search_tianapi_news(query, num=10):
    """同时搜索国内新闻和综合新闻API"""
    results = []
    # 国内新闻API
    results.extend(_search_tianapi("guonei", query, num=num))
    time.sleep(random.uniform(0.3, 0.6))
    # 综合新闻API（数据范围更广，覆盖科技频道）
    results.extend(_search_tianapi("generalnews", query, num=num))
    return results


# ============ 数据源2: 36氪RSS（科技资讯） ============

def search_36kr_rss(max_results=30):
    """
    36氪RSS订阅
    国内可直连，返回科技/创业类资讯
    不支持关键词搜索，返回最新文章后本地过滤
    """
    results = []
    try:
        url = "https://36kr.com/feed"
        data = http_get(url)
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
            pub_date = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ""

            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": desc[:200] if desc else "",
                    "pub_date": pub_date,
                    "source": "36氪",
                })

        print(f"    36氪RSS: {len(results)}条")

    except Exception as e:
        print(f"    36氪RSS异常: {e}")

    return results


# ============ 数据源3: InfoQ中文RSS（技术资讯） ============

def search_infoq_rss(max_results=20):
    """
    InfoQ中文RSS
    国内可直连，返回技术/架构类资讯
    """
    results = []
    try:
        url = "https://www.infoq.cn/feed"
        data = http_get(url)
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
            pub_date = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ""

            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": desc[:200] if desc else "",
                    "pub_date": pub_date,
                    "source": "InfoQ",
                })

        print(f"    InfoQ中文RSS: {len(results)}条")

    except Exception as e:
        print(f"    InfoQ中文RSS异常: {e}")

    return results


# ============ 数据源4: Solidot RSS（科技奇客） ============

def search_solidot_rss(max_results=20):
    """
    Solidot RSS
    国内可直连，科技/开源/奇客资讯
    """
    results = []
    try:
        url = "https://www.solidot.org/index.rss"
        data = http_get(url)
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
            pub_date = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ""

            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": desc[:200] if desc else "",
                    "pub_date": pub_date,
                    "source": "Solidot",
                })

        print(f"    Solidot RSS: {len(results)}条")

    except Exception as e:
        print(f"    Solidot RSS异常: {e}")

    return results


# ============ 数据源5: B站视频搜索 ============

def search_bilibili(query, num=10):
    """
    B站视频搜索API（/search/all/v2接口，无需Cookie即可使用）
    支持关键词搜索，返回视频标题、链接、播放量、发布时间
    国内直连，无需翻墙
    注意：请求间隔需>3秒避免风控
    """
    results = []
    try:
        params = {
            "keyword": query,
            "page": 1,
            "page_size": num,
            "order": "pubdate",  # 按发布时间排序，优先获取最新视频
        }
        url = "https://api.bilibili.com/x/web-interface/search/all/v2?" + urllib.parse.urlencode(params)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://search.bilibili.com/",
        }
        if BILIBILI_COOKIE:
            headers["Cookie"] = BILIBILI_COOKIE

        data = http_get(url, headers=headers)
        resp = json.loads(data.decode("utf-8"))

        if resp.get("code") != 0:
            print(f"    B站搜索返回: code={resp.get('code')}, msg={resp.get('message', '')}")
            return results

        # v2接口数据结构: data.result是数组，每项有result_type和data
        # 视频在result_type=="video"的项中
        result_groups = resp.get("data", {}).get("result", [])
        video_items = []
        for group in result_groups:
            if group.get("result_type") == "video":
                video_items = group.get("data", [])
                break

        if not video_items:
            print(f"    B站搜索 ({query}): 0条")
            return results

        for item in video_items[:num]:
            # B站标题含<em class="keyword">高亮标签，需清理
            title = clean_html(item.get("title", "")).strip()
            # B站返回的arcurl就是视频链接
            video_url = item.get("arcurl", "").strip()
            # 描述也含HTML标签
            description = clean_html(item.get("description", "")).strip()
            author = item.get("author", "").strip()
            play_count = item.get("play", 0)
            duration = item.get("duration", "").strip()
            # pubdate是Unix时间戳，转为日期字符串
            pub_timestamp = item.get("pubdate", 0)
            if pub_timestamp:
                pub_date = datetime.fromtimestamp(pub_timestamp, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
            else:
                pub_date = ""

            # 播放量格式化
            if isinstance(play_count, int) and play_count >= 10000:
                play_str = f"{play_count / 10000:.1f}万"
            else:
                play_str = str(play_count) if play_count else ""

            # 来源标签：B站 + 作者 + 播放量 + 时长
            source_parts = ["B站"]
            if author:
                source_parts.append(author)
            if play_str:
                source_parts.append(f"▶{play_str}")
            if duration:
                source_parts.append(duration)
            source = " · ".join(source_parts)

            if title and video_url:
                results.append({
                    "title": title,
                    "url": video_url,
                    "snippet": description[:200] if description else "",
                    "pub_date": pub_date,
                    "source": source,
                })

        print(f"    B站搜索 ({query}): {len(results)}条")

    except Exception as e:
        print(f"    B站搜索异常: {e}")

    return results


# ============ 统一搜索入口 ============

# 外骨骼相关关键词（用于天行数据API搜索和本地过滤）
SEARCH_KEYWORDS = [
    "外骨骼",
    "外骨骼机器人",
    "exoskeleton",
    "exoskeleton robot",
]

# 本地过滤关键词（用于RSS源标题+摘要匹配）
FILTER_KEYWORDS = [
    "外骨骼", "exoskeleton",
    "康复机器人", "助力机器人", "增强型机器人",
    "可穿戴机器人", "穿戴式助力",
    "动力外衣", "机械外衣",
    "人机增强", "人体增强",
]


def is_exoskeleton_related(title, snippet=""):
    """判断文章是否与外骨骼相关"""
    text = (title + " " + snippet).lower()
    for kw in FILTER_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def search_all():
    """使用国内数据源搜索外骨骼资讯"""
    all_results = []

    # 数据源1: 天行数据新闻API（主力，支持关键词搜索）
    if TIANAPI_KEY:
        print("\n📡 数据源1: 天行数据新闻API（主力）")
        for query in SEARCH_KEYWORDS:
            print(f"  搜索: {query}")
            results = search_tianapi_news(query, num=10)
            all_results.extend(results)
            time.sleep(random.uniform(0.5, 1.0))
    else:
        print("\n⚠️ 天行数据API未配置(TIANAPI_KEY)，跳过主力数据源")
        print("  免费注册获取key: https://www.tianapi.com")

    # 数据源2: 36氪RSS（本地过滤外骨骼相关）
    print("\n📡 数据源2: 36氪RSS")
    kr_results = search_36kr_rss(max_results=50)
    for r in kr_results:
        if is_exoskeleton_related(r["title"], r.get("snippet", "")):
            all_results.append(r)
    print(f"    36氪过滤后: {len([r for r in kr_results if is_exoskeleton_related(r['title'], r.get('snippet', ''))])}条")

    # 数据源3: InfoQ中文RSS（本地过滤）
    print("\n📡 数据源3: InfoQ中文RSS")
    infoq_results = search_infoq_rss(max_results=30)
    for r in infoq_results:
        if is_exoskeleton_related(r["title"], r.get("snippet", "")):
            all_results.append(r)
    print(f"    InfoQ过滤后: {len([r for r in infoq_results if is_exoskeleton_related(r['title'], r.get('snippet', ''))])}条")

    # 数据源4: Solidot RSS（本地过滤）
    print("\n📡 数据源4: Solidot RSS")
    solidot_results = search_solidot_rss(max_results=30)
    for r in solidot_results:
        if is_exoskeleton_related(r["title"], r.get("snippet", "")):
            all_results.append(r)
    print(f"    Solidot过滤后: {len([r for r in solidot_results if is_exoskeleton_related(r['title'], r.get('snippet', ''))])}条")

    # 数据源5: B站视频搜索（支持关键词搜索，结果直接归为video分类）
    print("\n📡 数据源5: B站视频搜索")
    for query in ["外骨骼", "外骨骼机器人", "exoskeleton"]:
        print(f"  搜索: {query}")
        bili_results = search_bilibili(query, num=10)
        # B站搜索结果直接是视频，标记为video分类
        for r in bili_results:
            r["category"] = "video"
        all_results.extend(bili_results)
        # B站请求间隔，避免风控
        time.sleep(random.uniform(3.0, 5.0))

    return all_results


# ============ 分类 ============

def categorize_item(title, snippet):
    """根据标题和内容分类"""
    text = (title + " " + snippet).lower()

    if any(kw in text for kw in ["bilibili", "哔哩哔哩", "b站", "抖音", "视频", "video", "youtube", "youku", "直播"]):
        return "video"

    if any(kw in text for kw in ["研究", "科研", "论文", "学术", "patent", "research", "study", "breakthrough", "中科院", "研究所", "university", "期刊", "nature", "science", "ieee", "journal", "专利", "突破", "成果"]):
        return "research"

    if any(kw in text for kw in ["融资", "投资", "轮", "产品", "发布", "launch", "funding", "investment", "series", "million", "billion", "product", "首发", "上市", "获投", "startup", "创企", "公司"]):
        return "company"

    return "news"


# ============ 去重 ============

def _title_similarity(title1, title2):
    """计算两个标题的相似度"""
    t1 = re.sub(r'[^\w\u4e00-\u9fff]', '', title1).lower()
    t2 = re.sub(r'[^\w\u4e00-\u9fff]', '', title2).lower()
    if not t1 or not t2:
        return 0.0
    if t1 in t2 or t2 in t1:
        return 1.0
    shorter, longer = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    max_match = 0
    for i in range(len(shorter)):
        for j in range(i + max_match + 1, len(shorter) + 1):
            if shorter[i:j] in longer:
                max_match = j - i
    return max_match / max(len(t1), len(t2))


def _extract_keywords(title):
    """从标题中提取关键词用于去重判断"""
    text = re.sub(r'[^\w\u4e00-\u9fff]', '', title).lower()
    keywords = set()
    for i in range(len(text) - 3):
        keywords.add(text[i:i+4])
    return keywords


def deduplicate(results):
    """按URL和标题去重（增强版）"""
    seen_urls = set()
    seen_titles = []
    unique = []

    for r in results:
        url = r.get("url", "")
        title = r.get("title", "").strip()

        # URL标准化去重（去掉查询参数中的追踪标识）
        normalized_url = re.sub(r'[?&](f=rss|utm_[^&=]+=[^&]*)', '', url)

        if normalized_url in seen_urls:
            continue

        title_simple = re.sub(r'[^\w\u4e00-\u9fff]', '', title).lower()
        is_duplicate = False

        if title_simple and title_simple in [re.sub(r'[^\w\u4e00-\u9fff]', '', st).lower() for st in seen_titles]:
            is_duplicate = True

        if not is_duplicate:
            for seen_title in seen_titles:
                if _title_similarity(title, seen_title) > 0.6:
                    is_duplicate = True
                    break

        if not is_duplicate:
            current_kw = _extract_keywords(title)
            for seen_title in seen_titles:
                seen_kw = _extract_keywords(seen_title)
                overlap = current_kw & seen_kw
                if len(overlap) >= 4:
                    is_duplicate = True
                    break

        if is_duplicate:
            continue

        seen_urls.add(normalized_url)
        if title_simple:
            seen_titles.append(title)

        unique.append(r)

    return unique


# ============ 推送历史（跨次运行去重） ============

def load_push_history():
    """加载推送历史，返回已推送的URL集合和标题列表"""
    pushed_urls = set()
    pushed_titles = []
    history = []

    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)

            now = datetime.now(CST)
            # 清理超过保留天数的历史记录
            valid_records = []
            for record in history:
                push_time_str = record.get("push_time", "")
                if push_time_str:
                    push_time = parse_date_flexible(push_time_str)
                    if push_time:
                        if push_time.tzinfo is None:
                            push_time = push_time.replace(tzinfo=CST)
                        if (now - push_time).days > HISTORY_RETAIN_DAYS:
                            continue
                valid_records.append(record)
                url = record.get("url", "")
                if url:
                    pushed_urls.add(url)
                title = record.get("title", "")
                if title:
                    pushed_titles.append(title)

            print(f"  加载推送历史: {len(valid_records)}条有效记录（保留{HISTORY_RETAIN_DAYS}天内）")
            # 保存清理后的历史
            history = valid_records
    except Exception as e:
        print(f"  加载推送历史异常: {e}")
        history = []

    return pushed_urls, pushed_titles, history


def filter_by_history(results, pushed_urls, pushed_titles):
    """过滤掉已推送过的资讯"""
    new_results = []
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "").strip()

        # URL完全匹配
        normalized_url = re.sub(r'[?&](f=rss|utm_[^&=]+=[^&]*)', '', url)
        if normalized_url and normalized_url in pushed_urls:
            continue

        # 标题相似度匹配
        title_simple = re.sub(r'[^\w\u4e00-\u9fff]', '', title).lower()
        is_dup = False
        if title_simple:
            for seen in pushed_titles:
                seen_simple = re.sub(r'[^\w\u4e00-\u9fff]', '', seen).lower()
                if title_simple == seen_simple:
                    is_dup = True
                    break
                if _title_similarity(title, seen) > 0.7:
                    is_dup = True
                    break
        if is_dup:
            continue

        new_results.append(r)

    filtered_count = len(results) - len(new_results)
    if filtered_count > 0:
        print(f"  历史去重: 过滤{filtered_count}条已推送资讯")

    return new_results


def save_push_history(history, new_results):
    """推送成功后更新历史文件"""
    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    for r in new_results:
        history.append({
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "push_time": now_str,
        })

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"  推送历史已保存: {len(history)}条记录")
    except Exception as e:
        print(f"  保存推送历史异常: {e}")


# ============ 时效性过滤 ============

def filter_recent(results, days=RECENT_DAYS):
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
            if source:
                meta_parts.append(source)
            if date_display:
                meta_parts.append(date_display)
            meta = f"（{' · '.join(meta_parts)}）" if meta_parts else ""

            url = item.get("url", "")
            if url:
                lines.append(f"{i}. [{item['title']}]({url}){meta}")
            else:
                lines.append(f"{i}. {item['title']}{meta}")
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


def send_markdown_to_wechat(content):
    """发送Markdown消息到企业微信群（支持可点击链接）"""
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


# ============ 主流程 ============

def main():
    print("=" * 50)
    print("外骨骼资讯推送脚本 v6 启动")
    print(f"版本特性: 跨次去重 + 国内直连数据源 + B站视频搜索，无需VPN")
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

    # 加载推送历史
    print("\n📖 加载推送历史...")
    pushed_urls, pushed_titles, history = load_push_history()

    # 搜索
    print("\n开始搜索（国内数据源）...")
    all_results = search_all()

    print(f"\n搜索总计: {len(all_results)} 条")

    # 去重（本次运行内去重）
    unique_results = deduplicate(all_results)
    print(f"去重后: {len(unique_results)} 条")

    # 时效性过滤（3天内）
    recent_results = filter_recent(unique_results, days=RECENT_DAYS)
    print(f"{RECENT_DAYS}天内: {len(recent_results)} 条")

    # 跨次运行去重（过滤已推送过的）
    print("\n🔍 跨次运行去重...")
    new_results = filter_by_history(recent_results, pushed_urls, pushed_titles)

    # 分类（B站结果已预设为video，保留不覆盖）
    for r in new_results:
        if r.get("category") != "video":
            r["category"] = categorize_item(r["title"], r.get("snippet", ""))

    # 排序：视频 > 科研 > 资讯 > 公司
    category_order = {"video": 0, "research": 1, "news": 2, "company": 3}
    new_results.sort(key=lambda x: category_order.get(x["category"], 99))

    print(f"\n最终推送: {len(new_results)} 条新资讯")

    # 没有新资讯，跳过推送
    if not new_results:
        print("\n⏭️ 没有新的外骨骼资讯，本次跳过推送")
        # 仍然保存历史（清理过期记录）
        save_push_history(history, [])
        return

    # 构建消息
    content = build_push_content(new_results, push_index)

    print("\n推送内容预览:")
    print("-" * 50)
    preview = content[:800] + "..." if len(content) > 800 else content
    print(preview)
    print("-" * 50)

    # 企业微信markdown消息限制2048字符
    if len(content) > 2000:
        content = content[:1990] + "\n...更多内容下期见"
        print("消息过长，已截断")

    # 发送（markdown消息类型支持可点击链接）
    print("\n正在推送到企业微信群...")
    success = send_markdown_to_wechat(content)

    if success:
        # 推送成功，保存历史
        save_push_history(history, new_results)
        print("✅ 推送完成")
    else:
        print("❌ 推送失败，不更新历史（下次重试）")
        sys.exit(1)


if __name__ == "__main__":
    main()
