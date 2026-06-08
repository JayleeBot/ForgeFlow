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
