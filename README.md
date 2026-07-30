# 📡 AI Dispatch

> 🇨🇳 [**中文版**](README.zh.md)

**Your daily AI intelligence briefing, delivered to Lark (Feishu).**

Automatically aggregates the latest in AI, Robotics, and Agents every morning — analyzed by an LLM of your choice, published as a Lark cloud doc with a bot link notification. Runs entirely on GitHub Actions. No server. Cheap subscription with [DeepSeek](https://api-docs.deepseek.com/).

![Workflow](assets/workflow.svg)

---

## What You Get

Every digest contains five structured sections:

| Section                 | Content                                                                          |
| ----------------------- | -------------------------------------------------------------------------------- |
| 📌 Top Stories          | 10–15 curated items, each with significance analysis and cross-story connections |
| 📈 Trend Analysis       | Cross-article patterns with evidence and forward predictions                     |
| 🔬 Papers Worth Reading | Selected arXiv papers with core contributions and reading focus                  |
| 📖 Blog Pick            | One deep-read recommendation (never repeats, auto-deduped)                       |
| 💡 Today's Signal       | The one judgment that matters most today, in one sentence                        |

---

## Quick Start

No terminal required — everything runs in your browser.

### Prerequisites

- GitHub account (free)
- Lark (Feishu) app with `im:message` and `docx:document` permissions

---

### Step 1 — Fork this repo

Click **Fork** in the top right → create it under your own account.

---

### Step 2 — Run the Setup workflow

Go to **Actions → ⚙️ Setup → Run workflow** and fill in the form:

| Field           | What to enter                                                                  |
| --------------- | ------------------------------------------------------------------------------ |
| Send time (UTC) | hour 0–23 — Beijing 08:00 → `0`, London BST 07:00 → `6`, New York 07:00 → `11` |
| DeepSeek model  | `deepseek-v4-flash` (default), `deepseek-v4-pro`, etc.                         |
| Output language | `English` or `中文`                                                            |

The workflow updates `config.yml` and prints a checklist of the secrets you need to add next.

---

### Step 3 — Add secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**

Add these **5 secrets** (the Setup workflow tells you exactly what to put in each):

| Secret              | Value                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------- |
| `DEEPSEEK_API_KEY`  | API key from [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) |
| `LARK_APP_ID`       | App ID from [open.feishu.cn/app](https://open.feishu.cn/app)                          |
| `LARK_SECRET`       | App secret from the same Feishu app                                                   |
| `LARK_FOLDER_TOKEN` | Cloud folder token for doc storage (see [docs/lark-doc.md](docs/lark-doc.md))         |
| `LARK_RECEIVER`     | Recipient `union_id` (app needs `im:message` permission)                              |

---

### Step 4 — Verify

Go to **Actions → ✅ Check Setup → Run workflow**

```
── GitHub Secrets ──────────────────────────────────
  ✅  DEEPSEEK_API_KEY        (set)
  ✅  LARK_APP_ID             (set)
  ✅  LARK_SECRET             (set)
  ✅  LARK_RECEIVER           (set)
  ✅  LARK_FOLDER_TOKEN       (set)

── config.yml ──────────────────────────────────────
  ✅  config.yml found
  ✅  topics configured  (3 topics)
  ✅  news_feeds configured  (9 sources)
  ✅  blog_feeds configured  (8 blogs)

── DeepSeek API ─────────────────────────────────────
  ✅  API connection successful (deepseek-v4-flash)

── Lark ─────────────────────────────────────────────
  ✅  Lark configured
  ✅  Test Lark doc notification sent

══════════════════════════════════════════════════════
  🎉  All checks passed! Your daily digest starts tomorrow.
══════════════════════════════════════════════════════
```

Once all green, AI Dispatch runs automatically every day. The default send time targets **07:00 BST / 07:00 GMT** — change it via `send_hour_utc` in `config.yml`.

---

## Prefer the command line?

<details>
<summary>Set up locally with the interactive wizard (requires Git, Python 3.10+, and GitHub CLI).</summary>

### Step 0 — Install Git and GitHub CLI

#### Install Git

```bash
# macOS — comes pre-installed; if missing:
xcode-select --install
```

```powershell
# Windows
winget install Git.Git
```

```bash
# Linux (Debian / Ubuntu)
sudo apt install git
```

> **Windows:** After `winget` installs Git, **close and reopen your terminal** before continuing.

#### Install GitHub CLI

```bash
# macOS
brew install gh
```

```powershell
# Windows — open a new terminal after this completes
winget install GitHub.cli
```

```bash
# Linux (Debian / Ubuntu)
sudo apt install gh
```

> **Windows:** Same as above — **reopen your terminal** after installation so `gh` is on your PATH.

#### Log in to GitHub

```bash
gh auth login
```

Follow the prompts — select **GitHub.com → HTTPS → Login with a web browser**.

### Step 1 — Fork, clone, and launch

```bash
# macOS / Linux
gh repo fork AkatQuas/ai-dispatch --clone
cd ai-dispatch        # use the folder name printed by gh above
uv sync
uv run python setup.py
```

```powershell
# Windows
gh repo fork AkatQuas/ai-dispatch --clone
cd ai-dispatch        # use the folder name printed by gh above
uv sync
uv run python setup.py
```

> `gh` prints the local path after cloning, e.g. `Cloned fork's Git repository to ai-dispatch`.

The wizard asks a few questions and handles everything else — secrets, config, and push.

### Step 2 — Verify

Go to **Actions → ✅ Check Setup → Run workflow** and confirm all checks pass.

</details>

---

## Cost

GitHub Actions is always free. The only cost is the DeepSeek API call for each daily digest (typically a few cents per run).

| Model                                   | Notes                                                                 |
| --------------------------------------- | --------------------------------------------------------------------- |
| `deepseek-v4-flash` / `deepseek-v4-pro` | Newer V4 models — see [DeepSeek docs](https://api-docs.deepseek.com/) |

Change the model in `config.yml` under `digest.model`, or pass it in the **⚙️ Setup** workflow.

---

## File Structure

```
ai-dispatch/
├── config.yml              ← Your personalization (the only file to edit)
├── setup.py                ← Interactive setup wizard
├── fetch_news.py           ← Main pipeline
├── lark_doc.py             ← Lark cloud doc create + markdown write
├── lark_notify.py          ← Doc report + bot link notification
├── send_lark_message.py    ← Lark bot messaging
├── llm.py                  ← DeepSeek API client
├── check_setup.py          ← Setup verification script
├── issue_store.py          ← Persist state/reports via GitHub Issues
├── pyproject.toml          ← Dependencies (managed with uv)
├── uv.lock
├── requirements.txt        ← Legacy; CI uses uv.lock
└── .github/workflows/
    ├── daily_news.yml      ← Daily cron job
    ├── setup.yml           ← First-time setup wizard (browser-based)
    └── check_setup.yml     ← One-click setup check
```

Runtime files (`sent_history.json`, `report/*.md`) are gitignored. CI loads/saves them through Issues (`ai-dispatch-state`, `ai-dispatch-report`). On each run: ① `load` pulls state + recent reports → ② fetch/analyze/send → ③ `save` + `publish-today` push back to Issues.

---

## FAQ

**Q: Check Setup passed but no daily digest?**
Check Actions → AI Dispatch for errors. GitHub Actions cron can occasionally delay 15–30 minutes.

**Q: Lark message not received?**
Confirm `LARK_RECEIVER` is the recipient's union_id, `LARK_FOLDER_TOKEN` is set, and the app has `im:message` and `docx:document` permissions enabled.

**Q: How do I change the output language?**
Edit `output_language` in `config.yml`. Default is `English` — change it to `中文` for Chinese output. The setup wizard also lets you choose during initial setup.

**Q: How do I add my own RSS sources?**
Add a line under `news_feeds` or `blog_feeds` in `config.yml`: `Source Name: https://rss-url`.

**Q: Blog picks keep repeating?**
Dedup state lives in the Issue labeled `ai-dispatch-state`. Clear the `urls` array in that Issue body (or locally in `sent_history.json` then run `python issue_store.py save`).

---

[🇨🇳 中文版 → README.zh.md](README.zh.md)
