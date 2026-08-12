"""Unit tests for fetch_news digest helpers."""

import unittest

from ai_dispatch.fetch_news import is_digest_complete, summarize_report_for_dedup

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


if __name__ == "__main__":
    unittest.main()
