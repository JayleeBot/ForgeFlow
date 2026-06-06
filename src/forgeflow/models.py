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
    supplier_name: str | None
    supplier_email: str | None
    price_breaks: str | None
    production_lead_time: str | None
    long_lead_time_parts: str | None
    moq: str | None
    payment_terms: str | None
    nre: str | None
    coo: str | None
    missing_fields: str | None
    next_action: str | None
    summary: str | None
    last_message_at: datetime
    last_followup_sent_at: datetime | None = None
    followup_count: int = 0


@dataclass(slots=True)
class Draft:
    thread_id: str
    draft_type: str
    recipient: str
    subject: str
    body: str
    status: str
