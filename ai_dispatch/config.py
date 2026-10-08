"""Typed application config loaded from config.yml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai_dispatch.llm import DEFAULT_MODEL
from ai_dispatch.paths import CONFIG_PATH


@dataclass
class MechanicalFilterConfig:
    """Deterministic filters before keyword rank and digest."""

    min_title_chars: int = 12
    min_keyword_score: int = 1
    t2_require_ai_signal: bool = True
    block_title_regex: list[str] = field(default_factory=list)
    report_title_dedup_threshold: float = 0.75
    dedupe_recent_reports: bool = True


@dataclass
class ClassicEntry:
    title: str
    url: str
    author: str = ""
    type: str = "classic"
    year: int | str = "经典"
    note: str = ""


@dataclass
class DigestConfig:
    save_raw_materials_doc: bool = True
    news_hours: int = 24
    blog_days: int = 90
    news_per_source: int = 50
    blog_per_source: int = 20
    news_max_items: int = 40
    blog_max_items: int = 25
    blog_classics_max: int = 3
    arxiv_max_items: int = 30
    fetch_max_workers: int = 3
    fetch_timeout_seconds: float = 15.0
    fetch_min_interval_seconds: float = 0.5
    require_published_date: bool = True
    hn_min_points: int = 5
    summary_max_chars: int = 400
    user_agent: str | None = None
    model: str = DEFAULT_MODEL
    reasoning_effort: str = "low"
    max_tokens: int = 16000
    report_history_max_chars: int = 2000
    output_language: str = "中文"

    def fetch_options(self) -> dict[str, Any]:
        """Options passed to feed_pipeline.fetch_feeds."""
        opts: dict[str, Any] = {
            "fetch_max_workers": self.fetch_max_workers,
            "fetch_timeout_seconds": self.fetch_timeout_seconds,
            "fetch_min_interval_seconds": self.fetch_min_interval_seconds,
            "require_published_date": self.require_published_date,
            "hn_min_points": self.hn_min_points,
            "summary_max_chars": self.summary_max_chars,
        }
        if self.user_agent is not None:
            opts["user_agent"] = self.user_agent
        return opts


@dataclass
class AppConfig:
    topics: list[str]
    news_feeds: dict[str, str]
    blog_feeds: dict[str, str]
    arxiv_keywords: list[str]
    digest: DigestConfig
    classics: list[ClassicEntry] = field(default_factory=list)
    mechanical_filter: MechanicalFilterConfig = field(default_factory=MechanicalFilterConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        digest_raw = data.get("digest") or {}
        mechanical_raw = dict(data.get("mechanical_filter") or {})
        # Legacy config: min_keyword_score / dedupe lived under removed `selection` key.
        legacy_selection = data.get("selection") or {}
        if "min_keyword_score" in legacy_selection and "min_keyword_score" not in mechanical_raw:
            mechanical_raw["min_keyword_score"] = legacy_selection["min_keyword_score"]
        if "dedupe_recent_reports" in legacy_selection and "dedupe_recent_reports" not in mechanical_raw:
            mechanical_raw["dedupe_recent_reports"] = legacy_selection["dedupe_recent_reports"]
        classics = [
            ClassicEntry(
                title=c["title"],
                url=c["url"],
                author=c.get("author", ""),
                type=c.get("type", "classic"),
                year=c.get("year", "经典"),
                note=c.get("note", ""),
            )
            for c in (data.get("classics") or [])
        ]
        return cls(
            topics=list(data.get("topics") or []),
            news_feeds=dict(data.get("news_feeds") or {}),
            blog_feeds=dict(data.get("blog_feeds") or {}),
            arxiv_keywords=list(data.get("arxiv_keywords") or []),
            digest=DigestConfig(
                **{k: v for k, v in digest_raw.items() if k in DigestConfig.__dataclass_fields__}
            ),
            classics=classics,
            mechanical_filter=MechanicalFilterConfig(
                **{
                    k: v
                    for k, v in mechanical_raw.items()
                    if k in MechanicalFilterConfig.__dataclass_fields__
                }
            ),
        )


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or CONFIG_PATH
    with open(config_path, encoding="utf-8") as f:
        return AppConfig.from_dict(yaml.safe_load(f) or {})
