from __future__ import annotations

from pathlib import Path

from forgeflow.models import Draft, EmailMessage
from forgeflow.parser import parse_email_file


class LocalMailbox:
    def __init__(self, inbox_dir: Path, outbox_dir: Path) -> None:
        self.inbox_dir = inbox_dir
        self.outbox_dir = outbox_dir

    def fetch_messages(self) -> list[EmailMessage]:
        messages: list[EmailMessage] = []
        for path in sorted(self.inbox_dir.glob("*.eml")):
            messages.append(parse_email_file(path))
        return messages

    def send_draft(self, draft: Draft) -> Path:
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
        return out_path
