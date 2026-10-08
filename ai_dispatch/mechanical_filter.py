"""Rule-based filters after RSS fetch (AIHOT-style mechanical gate, no per-item LLM)."""

from __future__ import annotations

import re
import sys
from typing import Any

from ai_dispatch.config import AppConfig
from ai_dispatch.feed_pipeline import score_relevance, title_similarity

AI_SIGNAL_TERMS: tuple[str, ...] = (
    " ai",
    "artificial intelligence",
    "machine learning",
    "llm",
    "language model",
    "gpt",
    "claude",
    "gemini",
    "deepseek",
    "openai",
    "anthropic",
    "agent",
    "agentic",
    "multimodal",
    "transformer",
    "neural",
    "robot",
    "embodied",
    "alignment",
    "governance",
    "regulation",
    "privacy",
    "security",
    "gpu",
    "nvidia",
    "inference",
    "fine-tun",
)

# Official / research feeds skip the generic-media AI-signal gate.
_OFFICIAL_SOURCE_MARKERS: tuple[str, ...] = (
    "arxiv",
    "openai",
    "deepmind",
    "google",
    "nvidia",
    "hugging face",
    "microsoft research",
    "cohere",
    "stanford hai",
    "mit news",
    "aws machine learning",
    "cloudflare",
)

DEFAULT_BLOCK_TITLE_PATTERNS: tuple[str, ...] = (
    r"(?i)\bwe(?:'|')?re hiring\b",
    r"(?i)\b(job|careers) (alert|opening|posting)\b",
    r"(?i)\b(sponsored|advertorial|paid partnership)\b",
)


def is_official_source(source: str) -> bool:
    lowered = source.lower()
    return any(m in lowered for m in _OFFICIAL_SOURCE_MARKERS)


def has_ai_signal(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(term in lowered for term in AI_SIGNAL_TERMS)


def mechanical_reject_reason(item: dict[str, Any], cfg: AppConfig) -> str | None:
    mf = cfg.mechanical_filter
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    if not title or not url:
        return "missing title or url"
    if len(title) < mf.min_title_chars:
        return "title too short"

    patterns = [re.compile(p) for p in DEFAULT_BLOCK_TITLE_PATTERNS]
    for p in mf.block_title_regex:
        patterns.append(re.compile(p))
    for pattern in patterns:
        if pattern.search(title):
            return "blocked title pattern"

    kind = item.get("kind", "news")
    source = str(item.get("source", ""))
    if (
        mf.t2_require_ai_signal
        and kind not in ("arxiv", "classic")
        and not is_official_source(source)
    ):
        blob = f"{title} {item.get('summary', '')}"
        topics_score = score_relevance(blob, cfg.topics, cfg.arxiv_keywords)
        if topics_score <= 0 and not has_ai_signal(blob):
            return "no AI signal"

    return None


def apply_mechanical_filters(
    articles: list[dict[str, Any]],
    cfg: AppConfig,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    rejected = 0
    for item in articles:
        if mechanical_reject_reason(item, cfg):
            rejected += 1
            continue
        kept.append(item)
    if rejected:
        print(f"  Mechanical filter: dropped {rejected} item(s)", file=sys.stderr)
    return kept


def dedupe_against_titles(
    articles: list[dict[str, Any]],
    recent_titles: list[str],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    if not recent_titles:
        return articles
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in articles:
        title = item.get("title", "")
        if title and any(title_similarity(title, t) >= threshold for t in recent_titles):
            dropped += 1
            continue
        kept.append(item)
    if dropped:
        print(
            f"  Report dedup: dropped {dropped} item(s) similar to recent digest titles",
            file=sys.stderr,
        )
    return kept
