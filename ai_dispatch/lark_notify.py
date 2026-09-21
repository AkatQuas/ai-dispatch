"""Send Lark notifications as docx link + short text message."""

from __future__ import annotations

import os
from datetime import datetime

from ai_dispatch.lark_client import lark_configured
from ai_dispatch.lark_doc import create_doc_with_markdown
from ai_dispatch.send_lark_message import send_message


def send_report_as_doc(
    *,
    title: str,
    markdown: str,
    summary: str | None = None,
    receive_id: str | None = None,
) -> bool:
    """Create a Lark docx with markdown body, then send bot message with doc link."""
    if not lark_configured():
        print("[WARN] Lark not configured, skipping notification")
        return False

    recipient = receive_id or os.getenv("LARK_RECEIVER")
    if not recipient:
        print("[WARN] LARK_RECEIVER not set, skipping notification")
        return False

    try:
        doc_url = create_doc_with_markdown(
            title,
            markdown,
            recipient_union_id=recipient,
        )
    except Exception as e:
        print(f"[ERROR] create Lark document failed: {e}")
        return False

    intro = summary or title
    text = f"{intro}\n\nRead full digest: {doc_url}"
    return send_message(recipient, {"text": text}, msg_type="text")


def send_lark_digest(md_body: str) -> bool:
    """Create a Lark docx with the digest and send a bot message with the doc link."""
    if not lark_configured():
        print(
            "[INFO] Lark not configured "
            "(LARK_APP_ID / LARK_SECRET / LARK_RECEIVER / LARK_FOLDER_TOKEN), skipping."
        )
        return False

    doc_title = datetime.now().strftime("%Y-%m-%d")

    return send_report_as_doc(
        title=doc_title,
        markdown=md_body.strip(),
        summary=doc_title,
    )
