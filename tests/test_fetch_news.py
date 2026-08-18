"""Unit tests for fetch_news digest helpers."""

import unittest

from ai_dispatch.fetch_news import (
    format_raw_materials_markdown,
    is_digest_complete,
    save_raw_materials_enabled,
    summarize_report_for_dedup,
)

SAMPLE_REPORT = """# AI News 2026年08月07日

> 新闻 23 条 · 博客 50 篇

## ★ 重点新闻

☆ [Kimi K3 Escape](https://example.com/kimi)
来源：Wired · 2026-08-07

**事件：** sandbox escape

**意义：** escape matters

## ★ 趋势分析

☆ Agent 安全
……

## ★ 值得深挖

☆ [Paper](https://arxiv.org/abs/1234)
……

## ★ 今日推荐博客

☆ [Blog Post](https://example.com/blog)
作者 · 2026

……为什么值得读……

## ★ 今日信号

alignment is not enough
"""


class ReportSummaryTests(unittest.TestCase):
    def test_summarize_extracts_title_items_and_signal(self):
        summary = summarize_report_for_dedup(SAMPLE_REPORT, max_chars=2000)
        self.assertIn("AI News 2026年08月07日", summary)
        self.assertNotIn("# AI News", summary)
        self.assertIn("- Kimi K3 Escape", summary)
        self.assertIn("- Blog Post", summary)
        self.assertIn("今日信号: alignment is not enough", summary)
        self.assertNotIn("sandbox escape", summary)

    def test_summarize_truncates_to_max_chars(self):
        summary = summarize_report_for_dedup(SAMPLE_REPORT, max_chars=40)
        self.assertLessEqual(len(summary), 40)
        self.assertTrue(summary.endswith("…"))

    def test_is_digest_complete(self):
        self.assertTrue(is_digest_complete(SAMPLE_REPORT))
        self.assertFalse(is_digest_complete("★ 重点新闻\nonly news"))

    def test_format_raw_materials_markdown(self):
        articles = [
            {
                "source": "Test News",
                "title": "Headline",
                "url": "https://example.com/news",
                "summary": "news summary",
                "published": "2026-08-07 10:00 UTC",
            }
        ]
        blogs = [
            {
                "source": "Blog · Author",
                "title": "Blog Post",
                "url": "https://example.com/blog",
                "summary": "blog note",
                "published": "2026-08-01",
            }
        ]
        cfg = {"digest": {"news_hours": 24}}
        md = format_raw_materials_markdown(articles, blogs, cfg)
        self.assertIn("## 新闻资讯", md)
        self.assertIn("## 博客/经典文章候选池", md)
        self.assertIn("Headline", md)
        self.assertIn("Blog Post", md)

    def test_save_raw_materials_enabled_defaults_true(self):
        self.assertTrue(save_raw_materials_enabled({}))
        self.assertTrue(save_raw_materials_enabled({"digest": {}}))
        self.assertFalse(
            save_raw_materials_enabled({"digest": {"save_raw_materials_doc": False}})
        )


if __name__ == "__main__":
    unittest.main()
