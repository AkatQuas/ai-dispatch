"""Unit tests for typed config."""

import unittest

from ai_dispatch.config import AppConfig, DigestConfig


class ConfigTests(unittest.TestCase):
    def test_from_dict_applies_digest_defaults(self):
        cfg = AppConfig.from_dict(
            {
                "topics": ["AI"],
                "news_feeds": {"Test": "https://example.com/feed"},
                "blog_feeds": {},
                "arxiv_keywords": ["agent"],
                "digest": {"news_hours": 12},
            }
        )
        self.assertEqual(cfg.topics, ["AI"])
        self.assertEqual(cfg.digest.news_hours, 12)
        self.assertEqual(cfg.digest.news_max_items, 40)

    def test_fetch_options_keys(self):
        opts = DigestConfig(fetch_max_workers=5).fetch_options()
        self.assertEqual(opts["fetch_max_workers"], 5)
        self.assertIn("hn_min_points", opts)
        self.assertNotIn("user_agent", opts)

    def test_fetch_options_includes_user_agent_when_set(self):
        opts = DigestConfig(user_agent="CustomBot/1.0").fetch_options()
        self.assertEqual(opts["user_agent"], "CustomBot/1.0")


if __name__ == "__main__":
    unittest.main()
