#!/usr/bin/env python3
"""
Persist runtime state and reports via GitHub Issues (no git commits).

Labels:
  ai-dispatch-state   — single Issue whose body is sent_history JSON
  ai-dispatch-report  — one Issue per daily report

Usage (CI):
  ai-dispatch-issues load          # state + recent reports → local files
  ai-dispatch-issues save          # local sent_history.json → state Issue
  ai-dispatch-issues publish-today # today's report/*.md → report Issue
  ai-dispatch-issues migrate       # publish all local report/*.md still missing

Outside Actions / without GH_TOKEN: load/save/publish no-op (local files only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ai_dispatch.paths import HISTORY_PATH, REPORT_DIR

LABEL_STATE = "ai-dispatch-state"
LABEL_REPORT = "ai-dispatch-report"
STATE_TITLE = "ai-dispatch runtime state (sent_history)"
DATE_MARKER_RE = re.compile(r"<!--\s*ai-dispatch-date:\s*(\d{4}-\d{2}-\d{2})\s*-->")
CN_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def gh_available() -> bool:
    if (
        not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        and os.environ.get("GITHUB_ACTIONS") == "true"
    ):
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result


def ensure_labels() -> None:
    for name, color, desc in (
        (LABEL_STATE, "0E8A16", "Runtime sent_history JSON for AI Dispatch"),
        (LABEL_REPORT, "1D76DB", "Daily AI Dispatch report archive"),
    ):
        r = run_gh(
            ["label", "create", name, "--color", color, "--description", desc],
            check=False,
        )
        msg = (r.stderr + r.stdout).lower()
        if r.returncode != 0 and "exists" not in msg:
            print(f"  ⚠  label create {name}: {r.stderr.strip() or r.stdout.strip()}")


def find_state_issue() -> int | None:
    r = run_gh(
        [
            "issue",
            "list",
            "--label",
            LABEL_STATE,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "1",
        ]
    )
    items = json.loads(r.stdout or "[]")
    return int(items[0]["number"]) if items else None


def empty_history() -> dict:
    return {"urls": [], "last_sent_date": ""}


def parse_state_body(body: str) -> dict:
    body = (body or "").strip()
    if not body:
        return empty_history()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", body, re.DOTALL)
    raw = fence.group(1) if fence else body
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("  ⚠  state Issue body is not valid JSON; using empty history")
        return empty_history()
    if not isinstance(data, dict):
        return empty_history()
    return {
        "urls": list(data.get("urls") or []),
        "last_sent_date": str(data.get("last_sent_date") or ""),
    }


def format_state_body(history: dict) -> str:
    payload = {
        "urls": history.get("urls") or [],
        "last_sent_date": history.get("last_sent_date") or "",
    }
    return (
        "<!-- managed by issue_store.py — do not edit by hand -->\n"
        "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"
    )


def load_state() -> None:
    """Pull state Issue → sent_history.json. Missing Issue → empty file."""
    if not gh_available():
        print("[issue_store] gh unavailable; keeping local sent_history.json")
        if not HISTORY_PATH.exists():
            HISTORY_PATH.write_text(
                json.dumps(empty_history(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return

    ensure_labels()
    number = find_state_issue()
    if number is None:
        print("[issue_store] no state Issue; writing empty sent_history.json")
        HISTORY_PATH.write_text(
            json.dumps(empty_history(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    r = run_gh(["issue", "view", str(number), "--json", "body"])
    body = json.loads(r.stdout)["body"] or ""
    history = parse_state_body(body)
    HISTORY_PATH.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"[issue_store] loaded state from #{number} "
        f"({len(history['urls'])} urls, last_sent={history['last_sent_date']!r})"
    )


def save_state() -> None:
    """Push local sent_history.json → state Issue (create if needed)."""
    if not gh_available():
        print("[issue_store] gh unavailable; skip save_state")
        return

    ensure_labels()
    if HISTORY_PATH.exists():
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    else:
        history = empty_history()

    body = format_state_body(history)
    number = find_state_issue()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(body)
        tmp_path = tmp.name

    try:
        if number is None:
            r = run_gh(
                [
                    "issue",
                    "create",
                    "--title",
                    STATE_TITLE,
                    "--body-file",
                    tmp_path,
                    "--label",
                    LABEL_STATE,
                ]
            )
            print(f"[issue_store] created state Issue: {r.stdout.strip()}")
        else:
            run_gh(["issue", "edit", str(number), "--body-file", tmp_path])
            print(f"[issue_store] updated state Issue #{number}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def extract_date_from_issue(title: str, body: str) -> str | None:
    m = DATE_MARKER_RE.search(body or "")
    if m:
        return m.group(1)
    m = CN_DATE_RE.search(title or "")
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m = ISO_DATE_RE.search(title or "")
    if m:
        return m.group(1)
    return None


def list_report_issues(limit: int = 50) -> list[dict]:
    r = run_gh(
        [
            "issue",
            "list",
            "--label",
            LABEL_REPORT,
            "--state",
            "all",
            "--json",
            "number,title,body,createdAt",
            "--limit",
            str(limit),
        ]
    )
    items = json.loads(r.stdout or "[]")

    # Prefer newer dates; fall back to createdAt
    def sort_key(it: dict) -> str:
        date = extract_date_from_issue(it.get("title") or "", it.get("body") or "")
        return date or (it.get("createdAt") or "")[:10]

    items.sort(key=sort_key, reverse=True)
    return items


def materialize_recent_reports(count: int = 3) -> None:
    """Write last N report Issues into report/YYYY-MM-DD.md."""
    if not gh_available():
        print("[issue_store] gh unavailable; keeping local report/")
        return

    ensure_labels()
    REPORT_DIR.mkdir(exist_ok=True)
    written = 0
    seen_dates: set[str] = set()
    for it in list_report_issues(limit=max(20, count * 3)):
        date = extract_date_from_issue(it.get("title") or "", it.get("body") or "")
        if not date or date in seen_dates:
            continue
        seen_dates.add(date)
        body = it.get("body") or ""
        # Strip our date marker line for cleaner LLM context
        body = DATE_MARKER_RE.sub("", body).lstrip("\n")
        path = REPORT_DIR / f"{date}.md"
        path.write_text(body, encoding="utf-8")
        print(f"[issue_store] materialized #{it['number']} → {path.name}")
        written += 1
        if written >= count:
            break
    if written == 0:
        print("[issue_store] no report Issues to materialize")


def get_issue_title_from_file(filepath: Path) -> str:
    first = filepath.read_text(encoding="utf-8").splitlines()[:1]
    title = first[0].lstrip("#").strip() if first else ""
    if not title:
        title = f"AI Dispatch Report - {filepath.stem}"
    return title[:120]


def report_issue_exists_for_date(date: str) -> bool:
    for it in list_report_issues(limit=30):
        if extract_date_from_issue(it.get("title") or "", it.get("body") or "") == date:
            print(f"[issue_store] report for {date} already exists as #{it['number']}")
            return True
    return False


def publish_report_file(filepath: Path) -> bool:
    """Create a report Issue from a markdown file. Returns True on success/skip."""
    date = filepath.stem
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        print(f"  -  skip non-date file: {filepath.name}")
        return True

    if report_issue_exists_for_date(date):
        return True

    raw = filepath.read_text(encoding="utf-8")
    body = f"<!-- ai-dispatch-date: {date} -->\n\n{raw}"
    title = get_issue_title_from_file(filepath)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(body)
        tmp_path = tmp.name
    try:
        r = run_gh(
            [
                "issue",
                "create",
                "--title",
                title,
                "--body-file",
                tmp_path,
                "--label",
                LABEL_REPORT,
            ]
        )
        print(f"[issue_store] published {filepath.name}: {r.stdout.strip()}")
        return True
    except RuntimeError as e:
        print(f"  ⚠  failed to publish {filepath.name}: {e}")
        return False
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def publish_today_report() -> None:
    if not gh_available():
        print("[issue_store] gh unavailable; skip publish_today")
        return
    ensure_labels()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = REPORT_DIR / f"{today}.md"
    if not path.exists():
        print(f"[issue_store] no report file for today ({path.name}); skip")
        return
    publish_report_file(path)


def migrate_local_reports() -> int:
    """Publish every local report/*.md that is not yet an Issue. Returns error count."""
    if not gh_available():
        print("[issue_store] gh unavailable; cannot migrate")
        return 1
    ensure_labels()
    REPORT_DIR.mkdir(exist_ok=True)
    errors = 0
    for path in sorted(REPORT_DIR.glob("*.md")):
        if not publish_report_file(path):
            errors += 1
    return errors


def label_existing_archive_issues() -> None:
    """Add ai-dispatch-report to legacy archive Issues (by Chinese/ISO date in title)."""
    if not gh_available():
        return
    ensure_labels()
    r = run_gh(
        [
            "issue",
            "list",
            "--state",
            "all",
            "--json",
            "number,title,labels",
            "--limit",
            "100",
        ]
    )
    for it in json.loads(r.stdout or "[]"):
        labels = {lb["name"] for lb in (it.get("labels") or [])}
        if LABEL_REPORT in labels or LABEL_STATE in labels:
            continue
        title = it.get("title") or ""
        if not (CN_DATE_RE.search(title) or title.startswith("AI News")):
            continue
        run_gh(["issue", "edit", str(it["number"]), "--add-label", LABEL_REPORT])
        print(f"[issue_store] labeled #{it['number']} as {LABEL_REPORT}")


def cmd_load(_: argparse.Namespace) -> int:
    load_state()
    materialize_recent_reports()
    return 0


def cmd_save(_: argparse.Namespace) -> int:
    save_state()
    return 0


def cmd_publish_today(_: argparse.Namespace) -> int:
    publish_today_report()
    return 0


def cmd_migrate(_: argparse.Namespace) -> int:
    label_existing_archive_issues()
    return migrate_local_reports()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_load = sub.add_parser("load", help="Load state + recent reports from Issues")
    p_load.set_defaults(func=cmd_load)

    p_save = sub.add_parser("save", help="Save sent_history.json to state Issue")
    p_save.set_defaults(func=cmd_save)

    p_pub = sub.add_parser("publish-today", help="Publish today's report as an Issue")
    p_pub.set_defaults(func=cmd_publish_today)

    p_mig = sub.add_parser("migrate", help="Label old Issues + publish local reports")
    p_mig.set_defaults(func=cmd_migrate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
