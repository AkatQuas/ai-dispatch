"""Lark SDK client adapter — sole owner of lark_oapi seam."""

import os

import lark_oapi as lark

_client: lark.Client | None = None


def lark_configured() -> bool:
    return bool(
        os.getenv("LARK_APP_ID")
        and os.getenv("LARK_SECRET")
        and os.getenv("LARK_RECEIVER")
        and os.getenv("LARK_FOLDER_TOKEN")
    )


def get_client() -> lark.Client:
    global _client
    if _client is None:
        _client = (
            lark.Client.builder()
            .app_id(os.environ["LARK_APP_ID"])
            .app_secret(os.environ["LARK_SECRET"])
            .log_level(lark.LogLevel.INFO)
            .build()
        )
    return _client
