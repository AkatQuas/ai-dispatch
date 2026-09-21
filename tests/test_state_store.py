"""Unit tests for state store interface."""

import unittest
from unittest.mock import patch

from ai_dispatch.state_store import InMemoryStateStore, IssueBackedStateStore


class StateStoreTests(unittest.TestCase):
    def test_history_round_trip(self):
        store = InMemoryStateStore()
        history = store.load_history()
        store.save_history(history, "https://example.com/blog")
        updated = store.load_history()
        self.assertIn("https://example.com/blog", updated["urls"])

    def test_reports_exclude_today_from_recent(self):
        store = InMemoryStateStore()
        store.save_report("today digest")
        store._reports["2026-01-01"] = "old digest"
        recent = store.load_recent_reports(count=3)
        self.assertEqual(recent, [("2026-01-01", "old digest")])


class IssueBackedStateStoreTests(unittest.TestCase):
    @patch("ai_dispatch.issue_store.materialize_recent_reports")
    @patch("ai_dispatch.issue_store.load_state")
    def test_load_history_syncs_from_remote(self, load_state, materialize):
        store = IssueBackedStateStore()
        store.load_history()
        load_state.assert_called_once()
        materialize.assert_called_once()

    @patch("ai_dispatch.issue_store.save_state")
    def test_save_history_syncs_to_remote(self, save_state):
        store = IssueBackedStateStore()
        store.save_history({"urls": [], "last_sent_date": ""}, "https://example.com/x")
        save_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
