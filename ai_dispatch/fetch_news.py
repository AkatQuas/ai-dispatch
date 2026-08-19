import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ai_dispatch.feed_pipeline import (
    build_classics,
    fetch_feeds,
    normalize_url,
    process_articles,
)
from ai_dispatch.issue_store import publish_today_report
from ai_dispatch.langfuse_tracing import observe
from ai_dispatch.lark_doc import create_doc_with_markdown
from ai_dispatch.llm import DEFAULT_MODEL, complete
from ai_dispatch.paths import CONFIG_PATH, HISTORY_PATH, REPORT_DIR
from ai_dispatch.send_lark_message import lark_configured, send_lark_digest

HISTORY_MAX = 200  # 最多保留最近 200 条（≈200 天），防止无限增长
REPORT_HISTORY_COUNT = 3  # 生成简报时参考最近几期，避免重复新闻
DIGEST_SECTION_MARKERS = (
    "## ★ 重点新闻",
    "## ★ 趋势分析",
    "## ★ 值得深挖",
    "## ★ 今日推荐博客",
    "## ★ 今日信号",
)


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return {"urls": [], "last_sent_date": ""}


def save_history(history: dict, new_url: str | None) -> None:
    urls = history.get("urls", [])
    if new_url:
        # 用 dict.fromkeys 保序去重（Python 3.7+ dict 有序）
        urls = list(dict.fromkeys([*urls, new_url]))
    if len(urls) > HISTORY_MAX:
        urls = urls[-HISTORY_MAX:]  # 保留最新的 N 条
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    HISTORY_PATH.write_text(
        json.dumps({"urls": urls, "last_sent_date": today}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_recent_reports(count: int = REPORT_HISTORY_COUNT) -> list[tuple[str, str]]:
    """Load the latest saved reports (date, content), excluding today."""
    if not REPORT_DIR.exists():
        return []

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    reports: list[tuple[str, str]] = []
    for path in sorted(REPORT_DIR.glob("*.md"), reverse=True):
        date = path.stem
        if date == today or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        reports.append((date, path.read_text(encoding="utf-8")))
        if len(reports) >= count:
            break
    return reports


def save_report(summary: str) -> Path:
    """Save today's digest to report/YYYY-MM-DD.md."""
    REPORT_DIR.mkdir(exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"{today}.md"
    path.write_text(summary, encoding="utf-8")
    return path


def extract_recommended_url(md: str) -> str | None:
    """从 digest markdown 的「今日推荐博客」小节中提取链接。"""
    match = re.search(
        r"(?:###?\s*📖\s*今日推荐博客|今日推荐博客).*?\[.*?\]\(([^)]+)\)",
        md,
        re.DOTALL,
    )
    return match.group(1) if match else None


def summarize_report_for_dedup(content: str, max_chars: int = 2000) -> str:
    """Compress a past report into titles + signal for lightweight dedup context."""
    lines: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(re.sub(r"^#+\s*", "", stripped))
            break

    for match in re.finditer(r"^☆\s+\[([^\]]+)\]\([^)]+\)", content, re.MULTILINE):
        lines.append(f"- {match.group(1)}")

    signal = re.search(
        r"^##\s*★\s*今日信号\s*\n+(.+?)(?=\n##\s|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if signal:
        signal_text = " ".join(signal.group(1).split())
        if signal_text:
            lines.append(f"今日信号: {signal_text}")

    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1] + "…"
    return summary


def is_digest_complete(md: str) -> bool:
    """True when all digest sections are present."""
    return all(marker in md for marker in DIGEST_SECTION_MARKERS)


def format_articles_text(articles: list[dict]) -> str:
    return "\n\n---\n\n".join(
        f"[{a['source']}] ({a['published']})\n标题: {a['title']}\n链接: {a['url']}\n摘要: {a['summary']}"
        for a in articles
    )


def format_blogs_text(
    blog_candidates: list[dict],
    *,
    empty_message: str = "（暂无候选，所有文章均已推送过）",
) -> str:
    if not blog_candidates:
        return empty_message
    return "\n\n---\n\n".join(
        f"[{b['source']}] ({b['published']})\n标题: {b['title']}\n链接: {b['url']}\n简介: {b['summary']}"
        for b in blog_candidates
    )


def format_raw_materials_markdown(
    articles: list[dict], blog_candidates: list[dict], cfg: dict
) -> str:
    d = cfg["digest"]
    today = datetime.now().strftime("%Y年%m月%d日")
    return f"""# AI Dispatch 原始资料 {today}

> 新闻 {len(articles)} 条 · 博客/经典 {len(blog_candidates)} 篇 · 新闻回溯 {d["news_hours"]} 小时

## 新闻资讯

{format_articles_text(articles)}

## 博客/经典文章候选池

{format_blogs_text(blog_candidates)}
"""


def save_raw_materials_enabled(cfg: dict) -> bool:
    return cfg.get("digest", {}).get("save_raw_materials_doc", True)


def save_raw_materials_doc(
    articles: list[dict], blog_candidates: list[dict], cfg: dict
) -> str | None:
    """Create a Lark docx with raw fetched materials (folder only, no notification)."""
    markdown = format_raw_materials_markdown(articles, blog_candidates, cfg)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    title = f"{today} 原始资料"

    try:
        return create_doc_with_markdown(title, markdown)
    except Exception as e:
        print(f"[WARN] Failed to create raw materials doc: {e}", file=sys.stderr)
        return None


def fetch_recent_articles(cfg: dict) -> list[dict]:
    """Fetch news RSS (parallel, rate-limited) → clean → dedup → rank → cap."""
    d = cfg["digest"]
    raw = fetch_feeds(
        cfg["news_feeds"],
        d["news_hours"],
        d["news_per_source"],
        cfg["arxiv_keywords"],
        d,
        feed_kind="news",
    )
    processed = process_articles(raw, cfg, pool="news")
    if len(raw) != len(processed):
        print(f"  News pipeline: {len(raw)} fetched → {len(processed)} for LLM")
    return processed


def fetch_blog_candidates(cfg: dict, history: set[str]) -> list[dict]:
    """抓取近 blog_days 天的博客 + 经典列表，过滤已推送过的。"""
    d = cfg["digest"]
    blog_hours = d["blog_days"] * 24
    history_norm = {normalize_url(url) for url in history}

    raw = fetch_feeds(
        cfg["blog_feeds"],
        blog_hours,
        d["blog_per_source"],
        cfg["arxiv_keywords"],
        d,
        feed_kind="blog",
    )
    blogs = process_articles(raw, cfg, pool="blog")
    if len(raw) != len(blogs):
        print(f"  Blog pipeline: {len(raw)} fetched → {len(blogs)} for LLM")
    blogs = [b for b in blogs if normalize_url(b["url"]) not in history_norm]

    classics_max = int(d.get("blog_classics_max", 3))
    classics = build_classics(cfg, history, classics_max)
    return blogs + classics


@observe(name="summarize-digest", capture_input=False)
def summarize(
    articles: list[dict],
    blog_candidates: list[dict],
    cfg: dict,
    recent_reports: list[tuple[str, str]] | None = None,
) -> str:
    d = cfg["digest"]
    model = d.get("model", DEFAULT_MODEL)

    topics_str = "、".join(cfg["topics"])
    lang = d.get("output_language", "中文")

    articles_text = format_articles_text(articles)
    blogs_text = format_blogs_text(blog_candidates)

    today = datetime.now().strftime("%Y年%m月%d日")

    if recent_reports:
        max_chars = d.get("report_history_max_chars", 2000)
        history_blocks = "\n\n---\n\n".join(
            f"【{date}】（已覆盖标题摘要）\n{summarize_report_for_dedup(content, max_chars)}"
            for date, content in recent_reports
        )
        history_section = f"""
【近几日简报回顾】以下是最近 {len(recent_reports)} 期已覆盖内容的标题摘要，请避免重复收录（除非有重要新进展）：

{history_blocks}

"""
    else:
        history_section = ""

    prompt = f"""你是 AI Dispatch 的主编，为顶级机构的同行撰写每日深度简报。
读者是熟悉该领域的专业人士，不需要解释基础概念，需要的是洞察和判断。
用户重点关注的方向：{topics_str}。
所有输出请使用{lang}。

### 核心规则
【重要规则】任何引用今日或近几日回归的内容（新闻、博客、论文、数据、动态）的地方，一律附上原始链接。没有来源链接的判断或引用不应出现。飞书文档支持 markdown 语法，使用 `[标题](链接)` 的格式。

### 历史报告
{history_section}

### 新闻资讯
过去 {d["news_hours"]} 小时，共 {len(articles)} 条：

{articles_text}

### 博客/经典文章候选池
# 共 {len(blog_candidates)} 篇（含近期博客、经典文章、访谈、大佬经验分享，均未推送过）：

{blogs_text}

### 输出要求
按照五个章节，严格使用 Markdown 格式输出（不要加代码块围栏、不要输出 HTML 标签）：

第一小节：重点新闻（10-15条，优先与用户关注方向相关）
每条包含：发生了什么（1句）、技术/商业意义（2-3句，要有判断和立场）、与其他动态的关联（如有）。

第二小节：趋势分析
识别 2-3 个值得关注的技术或行业趋势，需有证据引用（每条引用必须附链接），给出预判。

第三小节：值得深挖
2-3 篇值得精读的论文或报告（优先 arxiv），说明核心贡献和阅读重点，每篇必须附链接。

第四小节：今日推荐博客
从候选池中挑选 1 篇最值得精读的（可以是近期博客、经典文章、访谈或经验分享，不限时间）。
优先选择与今日新闻趋势有呼应的，或能提供长期视角的经典。
给出：为什么今天推荐这篇（结合当下背景）、3 个核心观点（bullet）、适合谁读、大致阅读时间。

第五小节：今日信号
最关键的一个判断，不超过 60 字。

以下为输出格式示例（仅作参考，你的正文不要包含代码块围栏）：

```markdown
# AI News {today}

> 新闻 {len(articles)} 条 · 博客 {len(blog_candidates)} 篇

## ★ 重点新闻

☆ [标题](URL)
来源：XXX · 时间

**事件：**……

**意义：**……

关联：……

## ★ 趋势分析

☆ 趋势名称
……

## ★ 值得深挖

☆ [论文/报告标题](URL)
……

## ★ 今日推荐博客

☆ [文章标题](URL)
作者/来源 · 时间

……为什么值得读……

- 核心观点一
- 核心观点二
- 核心观点三

适合：…… · 阅读时间：约 XX 分钟

## ★ 今日信号

……
```"""

    return complete(
        prompt,
        model=model,
        max_tokens=d["max_tokens"],
        reasoning_effort=d.get("reasoning_effort", "low"),
        is_complete=is_digest_complete,
        trace_metadata={
            "news_count": len(articles),
            "blog_count": len(blog_candidates),
            "recent_report_count": len(recent_reports or []),
        },
    )


def main() -> None:
    if not lark_configured():
        print(
            "[ERROR] Lark not configured. Set LARK_APP_ID, LARK_SECRET, "
            "LARK_RECEIVER, LARK_FOLDER_TOKEN.",
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

    recent_reports = load_recent_reports()
    if recent_reports:
        dates = ", ".join(date for date, _ in recent_reports)
        print(f"Loaded {len(recent_reports)} recent report(s) for dedup: {dates}")

    if save_raw_materials_enabled(cfg):
        print("Creating raw materials Lark doc...")
        raw_doc_url = save_raw_materials_doc(articles, blog_candidates, cfg)
        if raw_doc_url:
            print(f"Raw materials saved to {raw_doc_url}")
        else:
            print("[WARN] Raw materials doc creation failed, continuing with digest.")

    model = cfg["digest"].get("model", DEFAULT_MODEL)
    print(f"Summarizing with DeepSeek ({model})...")
    summary = summarize(articles, blog_candidates, cfg, recent_reports)

    report_path = save_report(summary)
    print(f"Saved report to {report_path}")

    print("Publishing report to GitHub Issue...")
    publish_today_report()

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


if __name__ == "__main__":
    main()
