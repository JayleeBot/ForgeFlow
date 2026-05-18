from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib import error, parse, request

from forgeflow.models import Draft, EmailMessage
from forgeflow.parser import parse_email_file


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\n{3,}")


class Mailbox(Protocol):
    def fetch_messages(self) -> list[EmailMessage]:
        ...

    def send_draft(self, draft: Draft) -> str:
        ...


class LocalMailbox:
    def __init__(self, inbox_dir: Path, outbox_dir: Path) -> None:
        self.inbox_dir = inbox_dir
        self.outbox_dir = outbox_dir

    def fetch_messages(self) -> list[EmailMessage]:
        messages: list[EmailMessage] = []
        for path in sorted(self.inbox_dir.glob("*.eml")):
            messages.append(parse_email_file(path))
        return messages

    def send_draft(self, draft: Draft) -> str:
        safe_thread = draft.thread_id.replace("/", "_")
        out_path = self.outbox_dir / f"{safe_thread}.txt"
        out_path.write_text(
            "\n".join(
                [
                    f"To: {draft.recipient}",
                    f"Subject: {draft.subject}",
                    "",
                    draft.body,
                ]
            ),
            encoding="utf-8",
        )
        return str(out_path)


@dataclass(slots=True)
class OutlookConfig:
    access_token: str
    mailbox_user: str
    folder: str
    top: int

    @classmethod
    def from_env(cls) -> "OutlookConfig":
        access_token = os.getenv("FORGEFLOW_OUTLOOK_ACCESS_TOKEN", "").strip()
        mailbox_user = os.getenv("FORGEFLOW_OUTLOOK_MAILBOX", "").strip()
        folder = os.getenv("FORGEFLOW_OUTLOOK_FOLDER", "Inbox").strip() or "Inbox"
        top_raw = os.getenv("FORGEFLOW_OUTLOOK_TOP", "25").strip()
        if not access_token:
            raise ValueError("FORGEFLOW_OUTLOOK_ACCESS_TOKEN is required for Outlook mode")
        if not mailbox_user:
            raise ValueError("FORGEFLOW_OUTLOOK_MAILBOX is required for Outlook mode")
        try:
            top = max(1, int(top_raw))
        except ValueError as exc:
            raise ValueError("FORGEFLOW_OUTLOOK_TOP must be an integer") from exc
        return cls(
            access_token=access_token,
            mailbox_user=mailbox_user,
            folder=folder,
            top=top,
        )


class OutlookMailbox:
    def __init__(self, config: OutlookConfig) -> None:
        self.config = config

    def fetch_messages(self) -> list[EmailMessage]:
        endpoint = (
            f"/users/{parse.quote(self.config.mailbox_user)}/mailFolders/"
            f"{parse.quote(self.config.folder)}/messages"
        )
        query = {
            "$top": str(self.config.top),
            "$orderby": "receivedDateTime desc",
            "$select": ",".join(
                [
                    "id",
                    "conversationId",
                    "internetMessageId",
                    "subject",
                    "from",
                    "toRecipients",
                    "receivedDateTime",
                    "body",
                ]
            ),
        }
        payload = self._get_json(endpoint, query)
        messages: list[EmailMessage] = []
        for item in payload.get("value", []):
            messages.append(self._normalize_message(item))
        messages.sort(key=lambda message: message.sent_at)
        return messages

    def send_draft(self, draft: Draft) -> str:
        endpoint = f"/users/{parse.quote(self.config.mailbox_user)}/sendMail"
        body = {
            "message": {
                "subject": draft.subject,
                "body": {"contentType": "Text", "content": draft.body},
                "toRecipients": [{"emailAddress": {"address": draft.recipient}}],
            },
            "saveToSentItems": True,
        }
        self._post_json(endpoint, body)
        return f"outlook://{self.config.mailbox_user}/{draft.thread_id}"

    def _normalize_message(self, item: dict) -> EmailMessage:
        sender = _format_sender(item.get("from", {}).get("emailAddress", {}))
        recipients = ", ".join(
            _format_recipient(recipient.get("emailAddress", {}))
            for recipient in item.get("toRecipients", [])
        )
        sent_at = _parse_graph_datetime(item.get("receivedDateTime"))
        body_text = _clean_graph_body(item.get("body", {}))
        message_id = (item.get("internetMessageId") or item.get("id") or "").strip()
        thread_id = (item.get("conversationId") or message_id).strip()
        return EmailMessage(
            message_id=message_id,
            thread_id=thread_id,
            subject=(item.get("subject") or "(no subject)").strip(),
            sender=sender or "unknown@example.com",
            recipients=recipients,
            sent_at=sent_at,
            body_text=body_text,
            source_path=f"outlook:{item.get('id', '')}",
        )

    def _get_json(self, endpoint: str, query: dict[str, str]) -> dict:
        url = f"{GRAPH_BASE_URL}{endpoint}?{parse.urlencode(query)}"
        req = request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        return self._execute(req)

    def _post_json(self, endpoint: str, body: dict) -> dict:
        url = f"{GRAPH_BASE_URL}{endpoint}"
        req = request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._execute(req)

    def _execute(self, req: request.Request) -> dict:
        try:
            with request.urlopen(req) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Microsoft Graph request failed with {exc.code}: {detail}"
            ) from exc
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


def build_mailbox(provider: str, inbox_dir: Path, outbox_dir: Path) -> Mailbox:
    normalized = provider.strip().lower()
    if normalized == "local":
        return LocalMailbox(inbox_dir, outbox_dir)
    if normalized == "outlook":
        return OutlookMailbox(OutlookConfig.from_env())
    raise ValueError(f"Unsupported mailbox provider: {provider}")


def _parse_graph_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _format_sender(email_address: dict) -> str:
    return _format_recipient(email_address)


def _format_recipient(email_address: dict) -> str:
    address = (email_address.get("address") or "").strip()
    name = (email_address.get("name") or "").strip()
    if name and address:
        return f'"{name}" <{address}>'
    return address


def _clean_graph_body(body: dict) -> str:
    content = body.get("content") or ""
    content_type = (body.get("contentType") or "text").lower()
    if content_type == "html":
        content = TAG_RE.sub(" ", html.unescape(content))
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = WHITESPACE_RE.sub("\n\n", content)
    return content.strip()
