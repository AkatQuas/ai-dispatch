"""Create Lark docx documents and write markdown content."""

from __future__ import annotations

import os
import time
import uuid

from lark_oapi.api.docx.v1 import (
    ConvertDocumentRequest,
    ConvertDocumentRequestBody,
    CreateDocumentBlockDescendantRequest,
    CreateDocumentBlockDescendantRequestBody,
    CreateDocumentRequest,
    CreateDocumentRequestBody,
)
from lark_oapi.api.drive.v1 import CreatePermissionMemberRequest
from lark_oapi.api.drive.v1.model.base_member import BaseMember

from send_lark_message import get_client

DOC_TYPE = "docx"
DEFAULT_DOMAIN = "feishu.cn"


def _folder_token() -> str:
    token = os.getenv("LARK_FOLDER_TOKEN")
    if not token or not token.strip():
        raise OSError("LARK_FOLDER_TOKEN is not set")
    return token.strip()


def document_url(document_id: str) -> str:
    domain = os.getenv("LARK_DOC_DOMAIN", DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN
    return f"https://{domain}/docx/{document_id}"


def create_document(title: str) -> tuple[str, int]:
    """Create an empty docx. Returns (document_id, revision_id)."""
    client = get_client()
    body = (
        CreateDocumentRequestBody.builder()
        .title(title)
        .folder_token(_folder_token())
        .build()
    )
    request = CreateDocumentRequest.builder().request_body(body).build()
    response = client.docx.v1.document.create(request)
    if not response.success():
        raise RuntimeError(
            f"create document failed: code={response.code}, msg={response.msg}, "
            f"log_id={response.get_log_id()}"
        )
    doc = response.data.document
    if doc is None or not doc.document_id:
        raise RuntimeError("create document failed: missing document_id")
    return doc.document_id, int(doc.revision_id or -1)


def _convert_markdown(markdown: str):
    client = get_client()
    request = (
        ConvertDocumentRequest.builder()
        .request_body(
            ConvertDocumentRequestBody.builder().content_type("markdown").content(markdown).build()
        )
        .build()
    )
    response = client.docx.v1.document.convert(request)
    if not response.success():
        raise RuntimeError(
            f"markdown convert failed: code={response.code}, msg={response.msg}, "
            f"log_id={response.get_log_id()}"
        )
    return response.data


def write_markdown(document_id: str, markdown: str, *, revision_id: int = -1) -> None:
    """Insert markdown body into a docx (root block = document_id)."""
    converted = _convert_markdown(markdown)
    blocks = converted.blocks or []
    children_id = converted.first_level_block_ids or []
    if not blocks or not children_id:
        print("[WARN] markdown convert returned empty blocks, skipping write")
        return

    client = get_client()
    request = (
        CreateDocumentBlockDescendantRequest.builder()
        .document_id(document_id)
        .block_id(document_id)
        .document_revision_id(revision_id)
        .client_token(str(uuid.uuid4()))
        .request_body(
            CreateDocumentBlockDescendantRequestBody.builder()
            .children_id(children_id)
            .index(0)
            .descendants(blocks)
            .build()
        )
        .build()
    )
    response = client.docx.v1.document_block_descendant.create(request)
    if not response.success():
        raise RuntimeError(
            f"write document failed: code={response.code}, msg={response.msg}, "
            f"log_id={response.get_log_id()}"
        )


def grant_permission(document_id: str, union_id: str, *, perm: str = "full_access") -> None:
    """Grant document access to a user by union_id."""
    client = get_client()
    request = (
        CreatePermissionMemberRequest.builder()
        .token(document_id)
        .type(DOC_TYPE)
        .need_notification(False)
        .request_body(
            BaseMember.builder().member_type("unionid").member_id(union_id).perm(perm).build()
        )
        .build()
    )
    response = client.drive.v1.permission_member.create(request)
    if not response.success():
        raise RuntimeError(
            f"grant permission failed: code={response.code}, msg={response.msg}, "
            f"log_id={response.get_log_id()}"
        )


def create_doc_with_markdown(
    title: str,
    markdown: str,
    *,
    recipient_union_id: str | None = None,
) -> str:
    """Create docx, write markdown, grant permission, return document URL."""
    document_id, revision_id = create_document(title)
    time.sleep(0.4)
    write_markdown(document_id, markdown, revision_id=revision_id)
    if recipient_union_id:
        time.sleep(0.4)
        try:
            grant_permission(document_id, recipient_union_id)
        except Exception as e:
            print(f"[WARN] document permission grant failed (link still returned): {e}")
    return document_url(document_id)
