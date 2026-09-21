import sys

from ai_dispatch.config import AppConfig, load_config
from ai_dispatch.digest import (
    extract_recommended_url,
    format_raw_materials_markdown,
    save_raw_materials_enabled,
    summarize,
)
from ai_dispatch.feed_pipeline import (
    build_classics,
    fetch_feeds,
    normalize_url,
    process_articles,
)
from ai_dispatch.issue_store import publish_today_report
from ai_dispatch.lark_client import lark_configured
from ai_dispatch.lark_doc import create_doc_with_markdown
from ai_dispatch.lark_notify import send_lark_digest
from ai_dispatch.llm import DEFAULT_MODEL
from ai_dispatch.state_store import REPORT_HISTORY_COUNT, StateStore, default_state_store


def fetch_recent_articles(cfg: AppConfig) -> list[dict]:
    """Fetch news RSS (parallel, rate-limited) → clean → dedup → rank → cap."""
    d = cfg.digest
    raw = fetch_feeds(
        cfg.news_feeds,
        d.news_hours,
        d.news_per_source,
        cfg.arxiv_keywords,
        d.fetch_options(),
        feed_kind="news",
    )
    processed = process_articles(raw, cfg, pool="news")
    if len(raw) != len(processed):
        print(f"  News pipeline: {len(raw)} fetched → {len(processed)} for LLM")
    return processed


def fetch_blog_candidates(cfg: AppConfig, history: set[str]) -> list[dict]:
    """抓取近 blog_days 天的博客 + 经典列表，过滤已推送过的。"""
    d = cfg.digest
    blog_hours = d.blog_days * 24
    history_norm = {normalize_url(url) for url in history}

    raw = fetch_feeds(
        cfg.blog_feeds,
        blog_hours,
        d.blog_per_source,
        cfg.arxiv_keywords,
        d.fetch_options(),
        feed_kind="blog",
    )
    blogs = process_articles(raw, cfg, pool="blog")
    if len(raw) != len(blogs):
        print(f"  Blog pipeline: {len(raw)} fetched → {len(blogs)} for LLM")
    blogs = [b for b in blogs if normalize_url(b["url"]) not in history_norm]

    classics = build_classics(cfg, history, d.blog_classics_max)
    return blogs + classics


def save_raw_materials_doc(
    articles: list[dict], blog_candidates: list[dict], cfg: AppConfig
) -> str | None:
    """Create a Lark docx with raw fetched materials (folder only, no notification)."""
    from datetime import UTC, datetime

    markdown = format_raw_materials_markdown(articles, blog_candidates, cfg)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    title = f"{today} 原始资料"

    try:
        return create_doc_with_markdown(title, markdown)
    except Exception as e:
        print(f"[WARN] Failed to create raw materials doc: {e}", file=sys.stderr)
        return None


def run_digest(store: StateStore | None = None) -> bool:
    """Core digest pipeline — accepts injectable state store for tests.

    Returns False when skipped (no content); True on success.
    """
    state = store or default_state_store()

    cfg = load_config()
    history = state.load_history()
    sent_urls = set(history.get("urls", []))

    print("Fetching news articles...")
    articles = fetch_recent_articles(cfg)
    print(f"Found {len(articles)} news articles")

    print("Fetching blog/classic candidates...")
    blog_candidates = fetch_blog_candidates(cfg, sent_urls)
    print(f"Found {len(blog_candidates)} unsent blog/classic candidates")

    if not articles and not blog_candidates:
        print("No content found, skipping.")
        return False

    recent_reports = state.load_recent_reports(REPORT_HISTORY_COUNT)
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

    model = cfg.digest.model or DEFAULT_MODEL
    print(f"Summarizing with DeepSeek ({model})...")
    summary = summarize(articles, blog_candidates, cfg, recent_reports)

    report_path = state.save_report(summary)
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
    state.save_history(history, recommended_url)

    print("Done!")
    return True


def main() -> None:
    if not lark_configured():
        print(
            "[ERROR] Lark not configured. Set LARK_APP_ID, LARK_SECRET, "
            "LARK_RECEIVER, LARK_FOLDER_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not run_digest():
        sys.exit(0)


if __name__ == "__main__":
    main()
