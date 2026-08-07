"""Project root paths (config and runtime data live beside the package)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yml"
ENV_PATH = ROOT / ".env"
HISTORY_PATH = ROOT / "sent_history.json"
REPORT_DIR = ROOT / "report"
