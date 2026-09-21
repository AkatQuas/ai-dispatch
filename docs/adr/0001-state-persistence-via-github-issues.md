# ADR-0001: State persistence via GitHub Issues

## Status

Accepted (2026-09-21)

## Context

AI Dispatch keeps two kinds of runtime state:

1. **Sent URL history** (`sent_history.json`) — blog URLs already recommended, plus `last_sent_date` for daily dedup.
2. **Report archive** (`report/YYYY-MM-DD.md`) — daily digest markdown for dedup context and GitHub Issue archive.

CI previously split persistence across three seams:

- `ai-dispatch-issues load` before `main()` (pull state + materialize recent reports)
- `fetch_news.main()` reading/writing local files only
- `ai-dispatch-issues save` after `main()` (push history to state Issue)

`main()` never called load itself; local dev and CI depended on different implicit contracts.

## Decision

Introduce a **`StateStore` interface** with **`IssueBackedStateStore`** as the production default:

| Operation | Local file | Remote (when `gh` available) |
|-----------|------------|------------------------------|
| `load_history()` | read `sent_history.json` | `issue_store.load_state()` first |
| `save_history()` | write `sent_history.json` | `issue_store.save_state()` after |
| `load_recent_reports()` | glob `report/*.md` | `materialize_recent_reports()` first |
| `save_report()` | write `report/YYYY-MM-DD.md` | unchanged; `publish_today_report()` stays in orchestration |

**Source of truth in CI:** GitHub Issues (labels `ai-dispatch-state`, `ai-dispatch-report`).

**Working copy at runtime:** local JSON + markdown files under the repo root.

**Local dev without `gh`:** `issue_store` functions no-op; `IssueBackedStateStore` behaves like `LocalStateStore`.

## Consequences

- `run_digest()` is self-contained: load and save sync through the store interface.
- CI keeps **`ai-dispatch-issues load`** before the dedup check (needs `last_sent_date` on disk before `main()`).
- CI **drops the separate `save` step** — `save_history()` inside `run_digest()` pushes to the state Issue.
- `ai-dispatch-issues save` remains available for manual repair / migration.
- Tests inject `InMemoryStateStore` or mock `sync_*` on `IssueBackedStateStore`.

## Alternatives considered

- **Issue-only store (no local files):** rejected — LLM dedup and debugging need local report files; `gh` subprocess on every read is slow.
- **Keep CI save step forever:** rejected — duplicates `IssueBackedStateStore.save_history()` with no extra safety once sync is in the store.
