"""Unit tests for RSS feed pipeline helpers."""

import unittest
from datetime import UTC, datetime

from ai_dispatch.feed_pipeline import (
    clean_html_text,
    deduplicate_articles,
    extract_radarai_summary,
    normalize_url,
    process_articles,
    rank_articles,
    score_relevance,
    title_similarity,
    truncate_summary,
)


class CleanHtmlTests(unittest.TestCase):
    def test_strips_tags_and_entities(self):
        raw = "<p>AI&#160;agents</p><strong>test</strong>"
        self.assertEqual(clean_html_text(raw), "AI agents test")

    def test_strips_hn_boilerplate(self):
        raw = (
            '<p>Article URL: <a href="https://example.com">link</a></p>'
            '<p>Comments URL: <a href="https://news.ycombinator.com/item?id=1">c</a></p>'
            "<p>Points: 1</p><p># Comments: 0</p>"
            "Actual summary here."
        )
        self.assertIn("Actual summary here", clean_html_text(raw))
        self.assertNotIn("Article URL", clean_html_text(raw))

    def test_extract_radarai_oneliner(self):
        text = "📌 一句话摘要\n            本文报道 OpenAI 暂停训练。\n        📝 详细摘要\n            很长..."
        self.assertEqual(extract_radarai_summary(text), "本文报道 OpenAI 暂停训练。")


class UrlTests(unittest.TestCase):
    def test_normalize_strips_tracking_and_www(self):
        url = "https://www.example.com/path/?utm_source=rss&ref=1"
        self.assertEqual(normalize_url(url), "https://example.com/path")


class ScoringTests(unittest.TestCase):
    def test_score_relevance_topics(self):
        score = score_relevance(
            "New AI agent harness for governance",
            ["AI Agents", "Governance"],
            [],
        )
        self.assertGreater(score, 0)

    def test_rank_caps_items(self):
        items = [
            {
                "title": f"item {i}",
                "summary": "",
                "url": f"https://example.com/{i}",
                "_published_dt": datetime(2026, 8, i + 1, tzinfo=UTC),
            }
            for i in range(10)
        ]
        ranked = rank_articles(items, [], [], max_items=3)
        self.assertEqual(len(ranked), 3)


class DedupTests(unittest.TestCase):
    def test_dedup_url_and_similar_title(self):
        items = [
            {
                "title": "OpenAI launches safer ChatGPT for teens",
                "summary": "",
                "url": "https://example.com/a",
                "_published_dt": datetime(2026, 8, 18, tzinfo=UTC),
            },
            {
                "title": "OpenAI launches safer ChatGPT for teens years later",
                "summary": "",
                "url": "https://example.com/b",
                "_published_dt": datetime(2026, 8, 17, tzinfo=UTC),
            },
        ]
        deduped = deduplicate_articles(items)
        self.assertEqual(len(deduped), 1)

    def test_title_similarity_high_for_overlap(self):
        self.assertGreater(
            title_similarity(
                "OpenAI launches ChatGPT for Teens",
                "OpenAI launches safer ChatGPT for teens",
            ),
            0.5,
        )


class ProcessTests(unittest.TestCase):
    def test_process_news_splits_arxiv_cap(self):
        cfg = {
            "topics": ["agent"],
            "arxiv_keywords": ["agent"],
            "digest": {
                "news_max_items": 2,
                "arxiv_max_items": 1,
            },
        }
        articles = [
            {
                "title": "arxiv paper on agents",
                "summary": "agent",
                "url": "https://arxiv.org/abs/1",
                "kind": "arxiv",
                "_published_dt": datetime(2026, 8, 19, tzinfo=UTC),
            },
            {
                "title": "another arxiv agent paper",
                "summary": "agent",
                "url": "https://arxiv.org/abs/2",
                "kind": "arxiv",
                "_published_dt": datetime(2026, 8, 18, tzinfo=UTC),
            },
            {
                "title": "news about agents",
                "summary": "agent",
                "url": "https://example.com/news",
                "kind": "news",
                "_published_dt": datetime(2026, 8, 19, tzinfo=UTC),
            },
        ]
        result = process_articles(articles, cfg, pool="news")
        self.assertEqual(len(result), 2)
        kinds = {r["kind"] for r in result}
        self.assertIn("arxiv", kinds)
        self.assertIn("news", kinds)


class UtilityTests(unittest.TestCase):
    def test_truncate_summary(self):
        self.assertTrue(truncate_summary("hello world", 8).endswith("…"))
        self.assertEqual(len(truncate_summary("hello world", 8)), 8)


if __name__ == "__main__":
    unittest.main()
