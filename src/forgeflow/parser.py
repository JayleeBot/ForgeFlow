from __future__ import annotations

import hashlib
import re
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from forgeflow.models import EmailMessage


FORWARD_PREFIX_RE = re.compile(r"^(re|fw|fwd):\s*", re.IGNORECASE)
QUOTED_LINE_RE = re.compile(r"^>+")
SIGNATURE_BREAK_RE = re.compile(r"^--\s*$")


def parse_email_file(path: Path) -> EmailMessage:
    raw = path.read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject = (message.get("Subject") or "(no subject)").strip()
    sender = (message.get("From") or "unknown@example.com").strip()
    recipients = ", ".join(message.get_all("To", []))
    sent_at = _parse_sent_at(message.get("Date"))
    body_text = _extract_text_body(message)
    message_id = (message.get("Message-ID") or _fallback_message_id(raw)).strip()
    thread_id = _thread_id_from_subject(subject, sender)
    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        sender=sender,
        recipients=recipients,
        sent_at=sent_at,
        body_text=body_text,
        source_path=str(path),
    )


def parse_email_text(raw_text: str, source_path: str = "manual") -> EmailMessage:
    raw = raw_text.encode("utf-8")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject = (message.get("Subject") or "(no subject)").strip()
    sender = (message.get("From") or "unknown@example.com").strip()
    recipients = ", ".join(message.get_all("To", []))
    sent_at = _parse_sent_at(message.get("Date"))
    body_text = _extract_text_body(message)
    message_id = (message.get("Message-ID") or _fallback_message_id(raw)).strip()
    thread_id = _thread_id_from_subject(subject, sender)
    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        sender=sender,
        recipients=recipients,
        sent_at=sent_at,
        body_text=body_text,
        source_path=source_path,
    )


def _parse_sent_at(raw_date: str | None) -> datetime:
    if not raw_date:
        return datetime.now().astimezone()
    try:
        return parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return datetime.now().astimezone()


def _extract_text_body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                return _clean_body(part.get_content())
        for part in message.walk():
            if part.get_content_type() == "text/html":
                return _clean_body(part.get_content())
    return _clean_body(message.get_content())


def _clean_body(body: str) -> str:
    cleaned_lines: list[str] = []
    for line in body.splitlines():
        if QUOTED_LINE_RE.match(line):
            continue
        if line.strip().startswith("On ") and "wrote:" in line:
            break
        if SIGNATURE_BREAK_RE.match(line.strip()):
            break
        cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip()


def _fallback_message_id(raw: bytes) -> str:
    digest = hashlib.sha1(raw).hexdigest()
    return f"<local-{digest}@forgeflow>"


def _thread_id_from_subject(subject: str, sender: str) -> str:
    normalized_subject = FORWARD_PREFIX_RE.sub("", subject).strip().lower()
    key = f"{normalized_subject}|{sender.lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
