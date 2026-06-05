import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

from llm import DEFAULT_MODEL, complete
from send_lark_message import lark_configured, send_lark_digest

HISTORY_PATH = Path(__file__).parent / "sent_history.json"
HISTORY_MAX = 1000  # 最多保留最近 1000 条，防止文件无限增长


def load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return {"urls": [], "last_sent_date": ""}


def save_history(history: dict, new_url: str | None) -> None:
    urls = set(history.get("urls", []))
    if new_url:
        urls.add(new_url)
    updated = list(urls)
    if len(updated) > HISTORY_MAX:
        updated = updated[-HISTORY_MAX:]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    HISTORY_PATH.write_text(
        json.dumps({"urls": updated, "last_sent_date": today}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_recommended_url(md: str) -> str | None:
    """从 digest markdown 的「今日推荐博客」小节中提取链接。"""
    match = re.search(
        r"(?:###?\s*📖\s*今日推荐博客|今日推荐博客).*?\[.*?\]\(([^)]+)\)",
        md,
        re.DOTALL,
    )
    return match.group(1) if match else None


def _fetch_feeds(feeds: dict, hours: int, per_source: int,
                 arxiv_keywords: list[str]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []

    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries[:per_source]:
                published = None
                for attr in ("published_parsed", "updated_parsed"):
                    t = getattr(entry, attr, None)
                    if t:
                        published = datetime(*t[:6], tzinfo=timezone.utc)
                        break

                if published and published < cutoff:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = (title + " " + summary).lower()

                if source.startswith("arxiv") and not any(kw in text for kw in arxiv_keywords):
                    continue

                articles.append({
                    "source": source,
                    "title": title,
                    "url": entry.get("link", ""),
                    "summary": summary[:1000] if summary else "",
                    "published": published.strftime("%Y-%m-%d %H:%M UTC") if published else "Unknown",
                })
        except Exception as e:
            print(f"[WARN] {source}: {e}", file=sys.stderr)

    return articles


def fetch_recent_articles(cfg: dict) -> list[dict]:
    d = cfg["digest"]
    return _fetch_feeds(
        cfg["news_feeds"], d["news_hours"], d["news_per_source"], cfg["arxiv_keywords"]
    )


def fetch_blog_candidates(cfg: dict, history: set[str]) -> list[dict]:
    """抓取近 blog_days 天的博客文章 + 读取经典列表，过滤已推送过的。"""
    d = cfg["digest"]
    blog_hours = d["blog_days"] * 24

    # RSS 博客
    rss_blogs = _fetch_feeds(
        cfg["blog_feeds"], blog_hours, d["blog_per_source"], cfg["arxiv_keywords"]
    )

    # 经典文章（无时间限制，从 config 读取）
    classics = [
        {
            "source": f"{c.get('type', 'classic').title()} · {c.get('author', '')}",
            "title": c["title"],
            "url": c["url"],
            "summary": c.get("note", ""),
            "published": str(c.get("year", "经典")),
        }
        for c in (cfg.get("classics") or [])
    ]

    # 合并后过滤历史
    all_candidates = rss_blogs + classics
    unsent = [a for a in all_candidates if a["url"] not in history]
    return unsent


def summarize(articles: list[dict], blog_candidates: list[dict], cfg: dict) -> str:
    d = cfg["digest"]
    model = d.get("model", DEFAULT_MODEL)

    topics_str = "、".join(cfg["topics"])
    lang = d.get("output_language", "中文")

    articles_text = "\n\n---\n\n".join(
        f"[{a['source']}] ({a['published']})\n标题: {a['title']}\n链接: {a['url']}\n摘要: {a['summary']}"
        for a in articles
    )
    blogs_text = "\n\n---\n\n".join(
        f"[{b['source']}] ({b['published']})\n标题: {b['title']}\n链接: {b['url']}\n简介: {b['summary']}"
        for b in blog_candidates
    ) if blog_candidates else "（暂无候选，所有文章均已推送过）"

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""你是 AI Dispatch 的主编，为顶级机构的同行撰写每日深度简报。
读者是熟悉该领域的专业人士，不需要解释基础概念，需要的是洞察和判断。
用户重点关注的方向：{topics_str}。
所有输出请使用{lang}。

【新闻资讯】过去 {d['news_hours']} 小时，共 {len(articles)} 条：

{articles_text}

【博客/经典文章候选池】共 {len(blog_candidates)} 篇（含近期博客、经典文章、访谈、大佬经验分享，均未推送过）：

{blogs_text}

请完成以下五个部分，严格使用 Markdown 格式输出（不要加代码块围栏、不要输出 HTML 标签）：

第一部分：重点新闻（10-15条，优先与用户关注方向相关）
每条包含：发生了什么（1句）、技术/商业意义（2-3句，要有判断和立场）、与其他动态的关联（如有）。

第二部分：趋势分析
识别 2-3 个值得关注的技术或行业趋势，需有证据引用，给出预判。

第三部分：值得深挖
2-3 篇值得精读的论文或报告（优先 arxiv），说明核心贡献和阅读重点。

第四部分：今日推荐博客
从候选池中挑选 1 篇最值得精读的（可以是近期博客、经典文章、访谈或经验分享，不限时间）。
优先选择与今日新闻趋势有呼应的，或能提供长期视角的经典。
给出：为什么今天推荐这篇（结合当下背景）、3 个核心观点（bullet）、适合谁读、大致阅读时间。

第五部分：今日信号
最关键的一个判断，不超过 60 字。

Markdown 格式模板：

📡 AI Dispatch · {today}

新闻 {len(articles)} 条 · 博客 {len(blog_candidates)} 篇 · 聚焦 {topics_str}

★ 重点新闻

☆ [标题（{lang}）](URL)
来源：XXX · 时间

**事件：**……

**意义：**……

关联：……

★ 趋势分析

☆ 趋势名称
……

★ 值得深挖

☆ [论文/报告标题](URL)
……

★ 今日推荐博客

☆ [文章标题](URL)
作者/来源 · 时间

……为什么值得读……

- 核心观点一
- 核心观点二
- 核心观点三

适合：…… · 阅读时间：约 XX 分钟

**今日信号：**……"""

    return complete(prompt, model=model, max_tokens=d["max_tokens"])


if __name__ == "__main__":
    if not lark_configured():
        print(
            "[ERROR] Lark not configured. Set LARK_APP_ID, LARK_SECRET, LARK_RECEIVER.",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = load_config()
    history = load_history()
    sent_urls = set(history.get("urls", []))

    print("Fetching news articles...")
    articles = fetch_recent_articles(cfg)
    print(f"Found {len(articles)} news articles")

    print("Fetching blog/classic candidates...")
    blog_candidates = fetch_blog_candidates(cfg, sent_urls)
    print(f"Found {len(blog_candidates)} unsent blog/classic candidates")

    if not articles and not blog_candidates:
        print("No content found, skipping.")
        sys.exit(0)

    model = cfg["digest"].get("model", DEFAULT_MODEL)
    print(f"Summarizing with DeepSeek ({model})...")
    summary = summarize(articles, blog_candidates, cfg)

    print("Sending Lark message...")
    if not send_lark_digest(summary):
        print("[ERROR] Lark message failed.", file=sys.stderr)
        sys.exit(1)

    recommended_url = extract_recommended_url(summary)
    if recommended_url:
        print(f"Recording recommended URL: {recommended_url}")
    else:
        print("[WARN] Could not extract recommended URL from output.")
    save_history(history, recommended_url)

    print("Done!")
