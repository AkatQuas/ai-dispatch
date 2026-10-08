"""Tests for mechanical ingest filters."""

import unittest

from ai_dispatch.config import AppConfig, DigestConfig, MechanicalFilterConfig
from ai_dispatch.mechanical_filter import (
    apply_mechanical_filters,
    dedupe_against_titles,
    has_ai_signal,
    mechanical_reject_reason,
)


def _cfg(**mf_kwargs) -> AppConfig:
    return AppConfig(
        topics=["AI Agents", "Security"],
        news_feeds={},
        blog_feeds={},
        arxiv_keywords=["agent"],
        digest=DigestConfig(),
        mechanical_filter=MechanicalFilterConfig(**mf_kwargs),
    )


class MechanicalFilterTests(unittest.TestCase):
    def test_has_ai_signal(self):
        self.assertTrue(has_ai_signal("New LLM benchmark for agents"))

    def test_rejects_short_title(self):
        item = {
            "title": "Hi",
            "url": "https://example.com/1",
            "summary": "agent security",
            "kind": "news",
            "source": "TechCrunch AI",
        }
        self.assertEqual(mechanical_reject_reason(item, _cfg()), "title too short")

    def test_media_requires_ai_signal(self):
        item = {
            "title": "Quarterly earnings beat expectations",
            "url": "https://example.com/2",
            "summary": "Revenue up across segments.",
            "kind": "news",
            "source": "TechCrunch AI",
        }
        self.assertEqual(mechanical_reject_reason(item, _cfg()), "no AI signal")

    def test_arxiv_exempt_from_signal_gate(self):
        item = {
            "title": "A long enough generic title here",
            "url": "https://arxiv.org/abs/1",
            "summary": "math",
            "kind": "arxiv",
            "source": "arxiv cs.AI",
        }
        self.assertIsNone(mechanical_reject_reason(item, _cfg()))

    def test_official_source_exempt(self):
        item = {
            "title": "Company updates quarterly guidance",
            "url": "https://openai.com/x",
            "summary": "Business update only.",
            "kind": "news",
            "source": "OpenAI News",
        }
        self.assertIsNone(mechanical_reject_reason(item, _cfg()))

    def test_dedupe_against_titles(self):
        items = [{"title": "OpenAI launches ChatGPT for Teens", "url": "https://a"}]
        out = dedupe_against_titles(
            items,
            ["OpenAI launches safer ChatGPT for teens"],
            threshold=0.75,
        )
        self.assertEqual(len(out), 0)

    def test_apply_mechanical_filters_drops(self):
        items = [
            {
                "title": "We're hiring engineers",
                "url": "https://example.com/j",
                "summary": "LLM team",
                "kind": "news",
                "source": "OpenAI News",
            },
            {
                "title": "New agent harness for security",
                "url": "https://example.com/g",
                "summary": "Governance tooling",
                "kind": "news",
                "source": "OpenAI News",
            },
        ]
        kept = apply_mechanical_filters(items, _cfg())
        self.assertEqual(len(kept), 1)
        self.assertIn("harness", kept[0]["title"])


if __name__ == "__main__":
    unittest.main()
