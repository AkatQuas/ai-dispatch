"""RSS fetch → clean → process pipeline for AI Dispatch raw materials."""

from __future__ import annotations

import html
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser

DEFAULT_USER_AGENT = "AI-Dispatch/0.1 (daily digest; +https://github.com/)"
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
HN_BOILERPLATE_RE = re.compile(
    r"<p>\s*Article URL:.*?</p>\s*<p>\s*Comments URL:.*?</p>\s*"
    r"<p>\s*Points:\s*\d+\s*</p>\s*<p>\s*#\s*Comments:\s*\d+\s*</p>",
    re.DOTALL | re.IGNORECASE,
)
HN_POINTS_RE = re.compile(r"Points:\s*(\d+)", re.IGNORECASE)
RADARAI_ONELINER_RE = re.compile(
    r"一句话摘要\s*\n+\s*(.+?)(?:\n+\s*📝|\n+\s*详细摘要|\Z)",
    re.DOTALL,
)
TITLE_DEDUP_THRESHOLD = 0.72


class RateLimiter:
    """Global minimum interval between HTTP requests (thread-safe)."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last = time.monotonic()


def normalize_url(url: str) -> str:
    """Canonicalize URL for dedup (scheme/host/path, drop common tracking params)."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query, keep_blank_values=False)
    for key in (
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "ref",
        "source",
    ):
        query.pop(key, None)
    clean_query = urlencode(query, doseq=True)
    return urlunparse((scheme, netloc, path, "", clean_query, ""))


def clean_html_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = HN_BOILERPLATE_RE.sub("", text)
    text = HTML_TAG_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def extract_radarai_summary(text: str) -> str:
    match = RADARAI_ONELINER_RE.search(text)
    if match:
        return WHITESPACE_RE.sub(" ", match.group(1)).strip()
    return text


def extract_entry_summary(entry: Any, source: str) -> str:
    summary = entry.get("summary", "") or ""
    if not summary:
        for content in entry.get("content", []) or []:
            value = content.get("value", "")
            if value:
                summary = value
                break
    cleaned = clean_html_text(summary)
    if "Radarai" in source or "bestblogs.dev" in summary:
        cleaned = extract_radarai_summary(cleaned)
    return cleaned


def parse_entry_date(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=UTC)
    return None


def hn_points_from_raw(entry: Any) -> int | None:
    raw = entry.get("summary", "") or ""
    match = HN_POINTS_RE.search(raw)
    return int(match.group(1)) if match else None


def title_tokens(title: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return {t for t in tokens if len(t) > 2}


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    return overlap / min(len(ta), len(tb))


def score_relevance(text: str, topics: list[str], extra_keywords: list[str]) -> int:
    lowered = text.lower()
    score = 0
    for topic in topics:
        topic = topic.strip().lower()
        if not topic:
            continue
        if topic in lowered:
            score += 3
        for token in re.findall(r"[a-z0-9]+", topic):
            if len(token) > 2 and token in lowered:
                score += 1
    for kw in extra_keywords:
        kw = kw.strip().lower()
        if kw and kw in lowered:
            score += 1
    return score


def truncate_summary(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def fetch_feed_bytes(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    rate_limiter: RateLimiter | None,
) -> bytes:
    rate_limiter = rate_limiter or RateLimiter(0)
    rate_limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_feed_entries(
    source: str,
    url: str,
    raw: bytes,
    *,
    cutoff: datetime | None,
    per_source: int,
    arxiv_keywords: list[str],
    require_published_date: bool,
    hn_min_points: int,
    summary_max_chars: int,
    feed_kind: str,
) -> list[dict]:
    feed = feedparser.parse(raw)
    if feed.bozo and feed.bozo_exception:
        print(
            f"[WARN] {source}: feed parse issue: {feed.bozo_exception}",
            file=sys.stderr,
        )

    windowed: list[tuple[Any, datetime | None]] = []
    for entry in feed.entries:
        published = parse_entry_date(entry)
        if cutoff and published and published < cutoff:
            continue
        if cutoff and not published and require_published_date:
            continue
        windowed.append((entry, published))

    articles: list[dict] = []
    for entry, published in windowed[:per_source]:
        title = clean_html_text(entry.get("title", ""))
        summary = extract_entry_summary(entry, source)
        url_link = entry.get("link", "") or ""
        text = f"{title} {summary}".lower()

        if source.lower().startswith("arxiv") and not any(kw in text for kw in arxiv_keywords):
            continue

        if "HackerNews" in source or "hnrss.org" in url:
            points = hn_points_from_raw(entry)
            if points is not None and points < hn_min_points:
                continue

        kind = "arxiv" if source.lower().startswith("arxiv") else feed_kind
        articles.append(
            {
                "source": source,
                "title": title,
                "url": url_link,
                "summary": truncate_summary(summary, summary_max_chars),
                "published": published.strftime("%Y-%m-%d %H:%M UTC") if published else "Unknown",
                "kind": kind,
                "_published_dt": published,
                "_score": 0,
            }
        )
    return articles


def _fetch_one_source(
    source: str,
    url: str,
    *,
    cutoff: datetime | None,
    per_source: int,
    arxiv_keywords: list[str],
    require_published_date: bool,
    hn_min_points: int,
    summary_max_chars: int,
    feed_kind: str,
    timeout: float,
    user_agent: str,
    rate_limiter: RateLimiter,
) -> tuple[str, list[dict], str | None]:
    try:
        raw = fetch_feed_bytes(
            url,
            timeout=timeout,
            user_agent=user_agent,
            rate_limiter=rate_limiter,
        )
        items = parse_feed_entries(
            source,
            url,
            raw,
            cutoff=cutoff,
            per_source=per_source,
            arxiv_keywords=arxiv_keywords,
            require_published_date=require_published_date,
            hn_min_points=hn_min_points,
            summary_max_chars=summary_max_chars,
            feed_kind=feed_kind,
        )
        return source, items, None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return source, [], str(e)


def fetch_feeds(
    feeds: dict[str, str],
    hours: int,
    per_source: int,
    arxiv_keywords: list[str],
    fetch_cfg: dict,
    *,
    feed_kind: str = "news",
) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours) if hours > 0 else None
    max_workers = int(fetch_cfg.get("fetch_max_workers", 3))
    timeout = float(fetch_cfg.get("fetch_timeout_seconds", 15))
    min_interval = float(fetch_cfg.get("fetch_min_interval_seconds", 0.5))
    require_published_date = bool(fetch_cfg.get("require_published_date", True))
    hn_min_points = int(fetch_cfg.get("hn_min_points", 5))
    summary_max_chars = int(fetch_cfg.get("summary_max_chars", 400))
    user_agent = fetch_cfg.get("user_agent", DEFAULT_USER_AGENT)

    rate_limiter = RateLimiter(min_interval)
    articles: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _fetch_one_source,
                source,
                url,
                cutoff=cutoff,
                per_source=per_source,
                arxiv_keywords=arxiv_keywords,
                require_published_date=require_published_date,
                hn_min_points=hn_min_points,
                summary_max_chars=summary_max_chars,
                feed_kind=feed_kind,
                timeout=timeout,
                user_agent=user_agent,
                rate_limiter=rate_limiter,
            ): source
            for source, url in feeds.items()
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                _, items, error = future.result()
                if error:
                    print(f"[WARN] {source}: {error}", file=sys.stderr)
                articles.extend(items)
            except Exception as e:
                print(f"[WARN] {source}: {e}", file=sys.stderr)

    return articles


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Drop duplicate URLs and near-duplicate titles (keep first / newest)."""
    sorted_items = sorted(
        articles,
        key=lambda a: a.get("_published_dt") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    seen_urls: set[str] = set()
    kept_titles: list[str] = []
    result: list[dict] = []

    for item in sorted_items:
        norm = normalize_url(item.get("url", ""))
        if norm and norm in seen_urls:
            continue
        title = item.get("title", "")
        if title and any(title_similarity(title, t) >= TITLE_DEDUP_THRESHOLD for t in kept_titles):
            continue
        if norm:
            seen_urls.add(norm)
        if title:
            kept_titles.append(title)
        result.append(item)
    return result


def rank_articles(
    articles: list[dict],
    topics: list[str],
    extra_keywords: list[str],
    *,
    max_items: int,
    arxiv_bonus: int = 2,
) -> list[dict]:
    if max_items <= 0:
        return []

    for item in articles:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        score = score_relevance(text, topics, extra_keywords)
        if item.get("kind") == "arxiv":
            score += arxiv_bonus
        item["_score"] = score

    ranked = sorted(
        articles,
        key=lambda a: (
            a.get("_score", 0),
            a.get("_published_dt") or datetime.min.replace(tzinfo=UTC),
        ),
        reverse=True,
    )
    return ranked[:max_items]


def strip_internal_fields(articles: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for item in articles:
        cleaned.append(
            {k: v for k, v in item.items() if not k.startswith("_")}
        )
    return cleaned


def process_articles(
    articles: list[dict],
    cfg: dict,
    *,
    pool: str,
) -> list[dict]:
    """Clean metadata, dedup, score, and cap for LLM input."""
    d = cfg.get("digest", {})
    topics = cfg.get("topics", [])
    keywords = cfg.get("arxiv_keywords", [])

    deduped = deduplicate_articles(articles)

    if pool == "news":
        arxiv_max = int(d.get("arxiv_max_items", 30))
        news_max = int(d.get("news_max_items", 40))
        arxiv_items = [a for a in deduped if a.get("kind") == "arxiv"]
        other_items = [a for a in deduped if a.get("kind") != "arxiv"]
        ranked = rank_articles(arxiv_items, topics, keywords, max_items=arxiv_max)
        ranked.extend(
            rank_articles(other_items, topics, keywords, max_items=news_max)
        )
        return strip_internal_fields(ranked)

    if pool == "blog":
        max_items = int(d.get("blog_max_items", 25))
    else:
        max_items = int(d.get("news_max_items", 40))

    ranked = rank_articles(deduped, topics, keywords, max_items=max_items)
    return strip_internal_fields(ranked)


def build_classics(cfg: dict, history: set[str], max_items: int) -> list[dict]:
    classics = [
        {
            "source": f"{c.get('type', 'classic').title()} · {c.get('author', '')}",
            "title": c["title"],
            "url": c["url"],
            "summary": c.get("note", ""),
            "published": str(c.get("year", "经典")),
            "kind": "classic",
        }
        for c in (cfg.get("classics") or [])
        if normalize_url(c["url"]) not in {normalize_url(u) for u in history}
    ]
    if max_items > 0:
        classics = classics[:max_items]
    return classics
