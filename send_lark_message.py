"""Lark (Feishu) message sending for AI Dispatch."""

import json
import os
import re
import time
from datetime import datetime

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
)

_client: lark.Client | None = None

LARK_CONTENT_MAX = 28000  # Lark message size limit (leave headroom)


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


def build_interactive_card(
    title: str,
    fields: list[dict],
    template: str = "wathet",
    actions: list[dict] | None = None,
) -> dict:
    elements = [
        {
            "tag": "div",
            "fields": [
                {"is_short": f["is_short"], "text": {"tag": "lark_md", "content": f["content"]}}
                for f in fields
            ],
        }
    ]

    if actions:
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "action",
                "layout": "bisected",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": a["text"]},
                        "type": a.get("type", "primary"),
                        "value": a.get("value", {}),
                    }
                    for a in actions
                ],
            }
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": elements,
    }


def send_message(
    receive_id: str,
    content: dict | str,
    msg_type: str = "text",
    max_retries: int = 3,
    retry_interval: int = 10,
) -> bool:
    client = get_client()

    if msg_type == "interactive":
        content_str = json.dumps(content) if isinstance(content, dict) else content
    else:
        content_str = json.dumps(content) if isinstance(content, dict) else content

    request: CreateMessageRequest = (
        CreateMessageRequest.builder()
        .receive_id_type("union_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type(msg_type)
            .content(content_str)
            .build()
        )
        .build()
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response: CreateMessageResponse = client.im.v1.message.create(request)

            if not response.success():
                last_error = (
                    f"code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
                )
                print(f"[WARN] Lark attempt {attempt}/{max_retries} failed: {last_error}")
            else:
                return True

        except Exception as e:
            last_error = str(e)
            print(f"[WARN] Lark attempt {attempt}/{max_retries} raised: {e}")

        if attempt < max_retries:
            time.sleep(retry_interval)

    print(f"[ERROR] Lark send failed after {max_retries} attempts: {last_error}")
    return False


def html_to_lark_md(html: str) -> str:
    """Convert digest HTML to Lark markdown (best-effort)."""
    text = html
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"## \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"### \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>\s*", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send_lark_digest(md_body: str) -> bool:
    """Create a Lark docx with the digest and send a bot message with the doc link."""
    from lark_notify import send_report_as_doc

    if not lark_configured():
        print(
            "[INFO] Lark not configured "
            "(LARK_APP_ID / LARK_SECRET / LARK_RECEIVER / LARK_FOLDER_TOKEN), skipping."
        )
        return False

    today = datetime.now().strftime("%m%d")
    title_match = re.search(r"^##\s+(.+)$", md_body, re.MULTILINE)
    doc_title = (
        title_match.group(1).strip() if title_match else f"{today} - AI Dispatch"
    )

    return send_report_as_doc(
        title=doc_title,
        markdown=md_body.strip(),
        summary=f"📰 {doc_title}",
    )
