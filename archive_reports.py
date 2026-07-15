#!/usr/bin/env python3
"""
Archive old report markdown files to GitHub Issues.

Usage:
    python archive_reports.py [--dry-run] [--days 7]

Scans report/*.md, creates a GitHub Issue for each file older than N days,
then removes the file from git.  Uses the `gh` CLI (pre-installed on GitHub
Actions runners, pre-authenticated via GITHUB_TOKEN).
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Archive old report markdown files to GitHub Issues"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Archive files older than this many days (default: 7)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be archived without creating issues or removing files"
    )
    parser.add_argument(
        "--report-dir", type=str, default="report",
        help="Directory containing report markdown files (default: report)"
    )
    return parser.parse_args()


def get_file_age_days(filepath: Path) -> int | None:
    """Extract date from filename YYYY-MM-DD.md and return age in days."""
    stem = filepath.stem  # filename without .md
    try:
        file_date = datetime.strptime(stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None  # filename doesn't match date pattern, skip

    age = datetime.now(timezone.utc) - file_date
    return age.days


def get_issue_title(filepath: Path) -> str:
    """Extract title from first line of markdown file, or fall back to filename."""
    with open(filepath, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    # Strip markdown heading markers and leading whitespace
    title = first_line.lstrip("#").strip()
    if not title:
        title = f"AI Dispatch Report - {filepath.stem}"
    # Truncate to 120 chars for GitHub issue title
    return title[:120]


def create_issue(filepath: Path, dry_run: bool) -> bool:
    """Create a GitHub Issue from the file content. Returns True on success."""
    title = get_issue_title(filepath)

    if dry_run:
        print(f"  [DRY RUN] Would create issue with title: {title}")
        return True

    result = subprocess.run(
        [
            "gh", "issue", "create",
            "--title", title,
            "--body-file", str(filepath),
        ],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  ✓  Issue created: {result.stdout.strip()}")
        return True
    else:
        print(f"  ⚠  Failed to create issue: {result.stderr.strip()}")
        return False


def remove_from_git(filepath: Path, dry_run: bool) -> bool:
    """git rm the file. Returns True on success."""
    if dry_run:
        print(f"  [DRY RUN] Would git rm: {filepath}")
        return True

    result = subprocess.run(
        ["git", "rm", str(filepath)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  ✓  Removed from git: {filepath}")
        return True
    else:
        print(f"  ⚠  Failed to git rm: {result.stderr.strip()}")
        return False

def check_gh_auth() -> None:
    """Verify gh CLI is authenticated and can create issues. Exit with clear message if not."""
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("❌  gh CLI is not authenticated.")
        print()
        print("    To fix, run:")
        print("      gh auth login", " # interactive browser login", sep="")
        print("    Or set a token:")
        print("      export GH_TOKEN=github_pat_...")
        print()
        sys.exit(1)


def main():
    args = parse_args()
    report_dir = Path(args.report_dir)
    cutoff_days = args.days

    if not report_dir.is_dir():
        print(f"Report directory not found: {report_dir}")
        sys.exit(0)

    md_files = sorted(report_dir.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {report_dir}")
        sys.exit(0)

    print(f"Scanning {len(md_files)} report file(s) in {report_dir}/")
    print(f"Archive threshold: > {cutoff_days} days old")
    if args.dry_run:
        print("*** DRY RUN — no changes will be made ***")
    else:
        check_gh_auth()
    print()

    archived = 0
    skipped = 0
    errors = 0

    for filepath in md_files:
        age_days = get_file_age_days(filepath)
        if age_days is None:
            print(f"  -  Skipping (non-date filename): {filepath.name}")
            skipped += 1
            continue
        if age_days <= cutoff_days:
            print(f"  ·  Skipping (only {age_days} day(s) old): {filepath.name}")
            skipped += 1
            continue

        print(f"▶  Archiving: {filepath.name} (age: {age_days} days)")

        if not create_issue(filepath, args.dry_run):
            errors += 1
            continue

        if not remove_from_git(filepath, args.dry_run):
            errors += 1
            continue

        archived += 1
        print()

    print("=" * 50)
    print(f"  Archived:  {archived}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    if args.dry_run:
        print("  *** DRY RUN — no changes were made ***")
    print("=" * 50)

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
