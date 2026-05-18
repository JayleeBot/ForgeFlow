from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class EmailMessage:
    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipients: str
    sent_at: datetime
    body_text: str
    source_path: str


@dataclass(slots=True)
class QuoteCase:
    thread_id: str
    status: str
    classification: str
    customer_name: str | None
    customer_email: str | None
    due_date: str | None
    part_numbers: str | None
    quantities: str | None
    missing_fields: str | None
    next_action: str | None
    summary: str | None
    last_message_at: datetime


@dataclass(slots=True)
class Draft:
    thread_id: str
    draft_type: str
    recipient: str
    subject: str
    body: str
    status: str
