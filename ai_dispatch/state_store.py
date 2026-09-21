"""State store interface — sent URL history and report archives."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from ai_dispatch.paths import HISTORY_PATH, REPORT_DIR

HISTORY_MAX = 200
REPORT_HISTORY_COUNT = 3


def empty_history() -> dict:
    return {"urls": [], "last_sent_date": ""}


class StateStore(ABC):
    """Interface for digest runtime state (history + reports)."""

    @abstractmethod
    def load_history(self) -> dict: ...

    @abstractmethod
    def save_history(self, history: dict, new_url: str | None = None) -> None: ...

    @abstractmethod
    def load_recent_reports(self, count: int = REPORT_HISTORY_COUNT) -> list[tuple[str, str]]: ...

    @abstractmethod
    def save_report(self, summary: str) -> Path: ...


class LocalStateStore(StateStore):
    """Filesystem-backed store (synced to GitHub Issues by issue_store CLI in CI)."""

    def __init__(
        self,
        *,
        history_path: Path = HISTORY_PATH,
        report_dir: Path = REPORT_DIR,
        history_max: int = HISTORY_MAX,
    ) -> None:
        self.history_path = history_path
        self.report_dir = report_dir
        self.history_max = history_max

    def load_history(self) -> dict:
        if self.history_path.exists():
            return json.loads(self.history_path.read_text(encoding="utf-8"))
        return empty_history()

    def save_history(self, history: dict, new_url: str | None = None) -> None:
        urls = list(history.get("urls") or [])
        if new_url:
            urls = list(dict.fromkeys([*urls, new_url]))
        if len(urls) > self.history_max:
            urls = urls[-self.history_max :]
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        payload = {"urls": urls, "last_sent_date": today}
        self.history_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_recent_reports(self, count: int = REPORT_HISTORY_COUNT) -> list[tuple[str, str]]:
        if not self.report_dir.exists():
            return []

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        reports: list[tuple[str, str]] = []
        for path in sorted(self.report_dir.glob("*.md"), reverse=True):
            date = path.stem
            if date == today or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                continue
            reports.append((date, path.read_text(encoding="utf-8")))
            if len(reports) >= count:
                break
        return reports

    def save_report(self, summary: str) -> Path:
        self.report_dir.mkdir(exist_ok=True)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        path = self.report_dir / f"{today}.md"
        path.write_text(summary, encoding="utf-8")
        return path


class IssueBackedStateStore(LocalStateStore):
    """Local files as working copy; sync to GitHub Issues when gh is available.

    See docs/adr/0001-state-persistence-via-github-issues.md.
    """

    def __init__(
        self,
        *,
        sync_reports_on_load: bool = True,
        report_history_count: int = REPORT_HISTORY_COUNT,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.sync_reports_on_load = sync_reports_on_load
        self.report_history_count = report_history_count

    def sync_from_remote(self) -> None:
        from ai_dispatch.issue_store import load_state, materialize_recent_reports

        load_state()
        if self.sync_reports_on_load:
            materialize_recent_reports(count=self.report_history_count)

    def sync_history_to_remote(self) -> None:
        from ai_dispatch.issue_store import save_state

        save_state()

    def load_history(self) -> dict:
        self.sync_from_remote()
        return super().load_history()

    def save_history(self, history: dict, new_url: str | None = None) -> None:
        super().save_history(history, new_url)
        self.sync_history_to_remote()

    def load_recent_reports(self, count: int = REPORT_HISTORY_COUNT) -> list[tuple[str, str]]:
        self.sync_from_remote()
        return super().load_recent_reports(count)


def default_state_store() -> StateStore:
    """Production store: local files + GitHub Issue sync when gh is configured."""
    return IssueBackedStateStore()


class InMemoryStateStore(StateStore):
    """In-memory store for tests."""

    def __init__(self) -> None:
        self._history = empty_history()
        self._reports: dict[str, str] = {}

    def load_history(self) -> dict:
        return dict(self._history)

    def save_history(self, history: dict, new_url: str | None = None) -> None:
        urls = list(history.get("urls") or [])
        if new_url:
            urls = list(dict.fromkeys([*urls, new_url]))
        self._history = {
            "urls": urls,
            "last_sent_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        }

    def load_recent_reports(self, count: int = REPORT_HISTORY_COUNT) -> list[tuple[str, str]]:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        items = [(d, c) for d, c in sorted(self._reports.items(), reverse=True) if d != today]
        return items[:count]

    def save_report(self, summary: str) -> Path:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        self._reports[today] = summary
        return Path(f"memory://{today}.md")
