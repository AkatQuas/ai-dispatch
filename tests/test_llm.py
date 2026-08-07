"""Unit tests for llm.complete multi-round handling."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_dispatch.llm import (
    CONTINUATION_PROMPT,
    MAX_COMPLETION_ROUNDS,
    _extract_content,
    _should_continue,
    _try_extract_content,
    complete,
)


def _message(*, content: str | None = None, reasoning: str | None = None):
    extra = {"reasoning_content": reasoning} if reasoning else {}
    return SimpleNamespace(content=content, model_extra=extra, tool_calls=None)


class ExtractContentTests(unittest.TestCase):
    def test_prefers_content_over_reasoning(self):
        msg = _message(content="final", reasoning="thinking")
        self.assertEqual(_try_extract_content(msg), "final")

    def test_reasoning_only_returns_none(self):
        msg = _message(content=None, reasoning="thinking")
        self.assertIsNone(_try_extract_content(msg))
        self.assertTrue(_should_continue(msg))

    def test_empty_raises(self):
        with self.assertRaisesRegex(RuntimeError, "empty content"):
            _extract_content(_message())


class CompleteTests(unittest.TestCase):
    @patch("ai_dispatch.llm.get_client")
    def test_returns_content_on_first_round(self, get_client):
        client = MagicMock()
        get_client.return_value = client
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=_message(content="digest"))]
        )

        result = complete("prompt", model="deepseek-v4-flash", max_tokens=100)

        self.assertEqual(result, "digest")
        client.chat.completions.create.assert_called_once()

    @patch("ai_dispatch.llm.get_client")
    def test_retries_when_only_reasoning_then_content(self, get_client):
        client = MagicMock()
        get_client.return_value = client
        client.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=_message(reasoning="step 1"))]),
            SimpleNamespace(choices=[SimpleNamespace(message=_message(content="digest"))]),
        ]

        result = complete("prompt", model="deepseek-v4-flash", max_tokens=100)

        self.assertEqual(result, "digest")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        second_messages = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertEqual(len(second_messages), 3)
        self.assertEqual(second_messages[2]["content"], CONTINUATION_PROMPT)

    @patch("ai_dispatch.llm.get_client")
    def test_raises_after_max_rounds_of_reasoning_only(self, get_client):
        client = MagicMock()
        get_client.return_value = client
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=_message(reasoning="still thinking"))]
        )

        with self.assertRaisesRegex(RuntimeError, f"{MAX_COMPLETION_ROUNDS} round"):
            complete("prompt", model="deepseek-v4-flash", max_tokens=100)

        self.assertEqual(client.chat.completions.create.call_count, MAX_COMPLETION_ROUNDS)


if __name__ == "__main__":
    unittest.main()
