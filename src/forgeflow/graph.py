from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from urllib.error import HTTPError
from html import unescape
from typing import Any

from forgeflow.auth import refresh_access_token
from forgeflow.models import EmailMessage


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
TAG_RE = re.compile(r"<[^>]+>")


class GraphMailbox:
    def __init__(
        self,
        access_token: str | None = None,
        mailbox: str | None = None,
        folder: str | None = None,
    ) -> None:
        self.access_token = access_token or os.environ["FORGEFLOW_OUTLOOK_ACCESS_TOKEN"]
        self.mailbox = mailbox or os.environ.get("FORGEFLOW_OUTLOOK_MAILBOX", "forgeflow.demo@outlook.com")
        self.folder = folder or os.environ.get("FORGEFLOW_OUTLOOK_FOLDER", "Inbox")
        self.auth_mode = os.environ.get("FORGEFLOW_OUTLOOK_AUTH_MODE", "app")

    def fetch_recent(self, top: int | None = None) -> list[EmailMessage]:
        top = top or int(os.environ.get("FORGEFLOW_OUTLOOK_TOP", "25"))
        folder = urllib.parse.quote(self.folder)
        select = ",".join([
            "id",
            "conversationId",
            "subject",
            "from",
            "toRecipients",
            "receivedDateTime",
            "body",
            "bodyPreview",
            "webLink",
        ])
        query = urllib.parse.urlencode({
            "$top": str(top),
            "$orderby": "receivedDateTime desc",
            "$select": select,
        })
        mailbox_path = "me" if self.auth_mode == "delegated" or self.mailbox == "me" else f"users/{urllib.parse.quote(self.mailbox)}"
        data = self._get(f"/{mailbox_path}/mailFolders/{folder}/messages?{query}")
        return [_message_from_graph(item) for item in data.get("value", [])]

    def reply(self, message_id: str, body_text: str) -> None:
        mailbox_path = "me" if self.auth_mode == "delegated" or self.mailbox == "me" else f"users/{urllib.parse.quote(self.mailbox)}"
        self._post(
            f"/{mailbox_path}/messages/{urllib.parse.quote(message_id, safe='')}/reply",
            {"comment": _reply_body(body_text)},
        )

    def _get(self, path: str) -> dict[str, Any]:
        return self._send("GET", path)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", path, payload)

    def _send(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(2):
            req = self._build_request(method, path, payload)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    body = response.read().decode("utf-8").strip()
                    return json.loads(body) if body else {}
            except HTTPError as exc:
                if exc.code == 401 and attempt == 0 and self._refresh():
                    continue
                body = exc.read().decode("utf-8", errors="replace").strip()
                detail = f": {body}" if body else ""
                raise RuntimeError(f"Microsoft Graph returned HTTP {exc.code}{detail}") from exc
        raise RuntimeError("Microsoft Graph request failed after token refresh")

    def _build_request(self, method: str, path: str, payload: dict[str, Any] | None) -> urllib.request.Request:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(f"{GRAPH_ROOT}{path}", data=data, headers=headers, method=method)

    def _refresh(self) -> bool:
        if self.auth_mode != "delegated":
            return False
        self.access_token = refresh_access_token()
        return True


def _message_from_graph(item: dict[str, Any]) -> EmailMessage:
    body = item.get("body") or {}
    body_text = body.get("content") or item.get("bodyPreview") or ""
    if body.get("contentType", "").lower() == "html":
        body_text = _html_to_text(body_text)
    return EmailMessage(
        message_id=item["id"],
        thread_id=item.get("conversationId") or item["id"],
        subject=(item.get("subject") or "(no subject)").strip(),
        sender=_email_address(item.get("from")),
        recipients=", ".join(_email_address(r) for r in item.get("toRecipients", [])),
        sent_at=_parse_graph_datetime(item.get("receivedDateTime")),
        body_text=body_text.strip(),
        source_path=item.get("webLink") or f"graph:{item['id']}",
    )


def _email_address(value: dict[str, Any] | None) -> str:
    email = (value or {}).get("emailAddress") or {}
    name = email.get("name")
    address = email.get("address") or "unknown@example.com"
    return f"{name} <{address}>" if name else address


def _parse_graph_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p\s*>", "\n\n", value)
    return unescape(TAG_RE.sub("", value))


def _reply_body(value: str) -> str:
    lines = value.splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        lines = lines[1:]
    return "\n".join(lines).strip()
