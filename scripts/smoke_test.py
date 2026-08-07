#!/usr/bin/env python3
"""Fast offline smoke test — used by pre-commit and CI."""

from __future__ import annotations

import unittest

from ai_dispatch.llm import DEFAULT_MODEL, api_key_configured
from ai_dispatch.paths import CONFIG_PATH


def main() -> None:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"missing {CONFIG_PATH}")

    if not DEFAULT_MODEL:
        raise SystemExit("DEFAULT_MODEL is empty")

    # Import side-effect-free modules used by the daily pipeline.
    import ai_dispatch.fetch_news
    import ai_dispatch.issue_store
    import ai_dispatch.langfuse_tracing  # noqa: F401

    _ = api_key_configured  # referenced to ensure public API is importable

    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    if not result.wasSuccessful():
        raise SystemExit("unit tests failed")

    print("smoke test passed")


if __name__ == "__main__":
    main()
