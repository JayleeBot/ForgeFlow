from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from forgeflow.models import Draft, EmailMessage, QuoteCase


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipients TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                body_text TEXT NOT NULL,
                source_path TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cases (
                thread_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                classification TEXT NOT NULL,
                customer_name TEXT,
                customer_email TEXT,
                due_date TEXT,
                part_numbers TEXT,
                quantities TEXT,
                missing_fields TEXT,
                next_action TEXT,
                summary TEXT,
                last_message_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                draft_type TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS case_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.conn.commit()

    def has_message(self, message_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return row is not None

    def save_message(self, message: EmailMessage) -> None:
        self.conn.execute(
            """
            INSERT INTO messages (
                message_id, thread_id, subject, sender, recipients,
                sent_at, body_text, source_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.thread_id,
                message.subject,
                message.sender,
                message.recipients,
                message.sent_at.isoformat(),
                message.body_text,
                message.source_path,
            ),
        )
        self.conn.commit()

    def list_thread_messages(self, thread_id: str) -> list[EmailMessage]:
        rows = self.conn.execute(
            """
            SELECT message_id, thread_id, subject, sender, recipients, sent_at,
                   body_text, source_path
            FROM messages
            WHERE thread_id = ?
            ORDER BY sent_at ASC
            """,
            (thread_id,),
        ).fetchall()
        return [
            EmailMessage(
                message_id=row["message_id"],
                thread_id=row["thread_id"],
                subject=row["subject"],
                sender=row["sender"],
                recipients=row["recipients"],
                sent_at=datetime.fromisoformat(row["sent_at"]),
                body_text=row["body_text"],
                source_path=row["source_path"],
            )
            for row in rows
        ]

    def list_thread_ids(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT thread_id FROM messages ORDER BY thread_id"
        ).fetchall()
        return [row["thread_id"] for row in rows]

    def upsert_case(self, case: QuoteCase) -> None:
        self.conn.execute(
            """
            INSERT INTO cases (
                thread_id, status, classification, customer_name, customer_email,
                due_date, part_numbers, quantities, missing_fields, next_action,
                summary, last_message_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                status = excluded.status,
                classification = excluded.classification,
                customer_name = excluded.customer_name,
                customer_email = excluded.customer_email,
                due_date = excluded.due_date,
                part_numbers = excluded.part_numbers,
                quantities = excluded.quantities,
                missing_fields = excluded.missing_fields,
                next_action = excluded.next_action,
                summary = excluded.summary,
                last_message_at = excluded.last_message_at
            """,
            (
                case.thread_id,
                case.status,
                case.classification,
                case.customer_name,
                case.customer_email,
                case.due_date,
                case.part_numbers,
                case.quantities,
                case.missing_fields,
                case.next_action,
                case.summary,
                case.last_message_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_case(self, thread_id: str) -> QuoteCase | None:
        row = self.conn.execute(
            """
            SELECT thread_id, status, classification, customer_name, customer_email,
                   due_date, part_numbers, quantities, missing_fields, next_action,
                   summary, last_message_at
            FROM cases
            WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return QuoteCase(
            thread_id=row["thread_id"],
            status=row["status"],
            classification=row["classification"],
            customer_name=row["customer_name"],
            customer_email=row["customer_email"],
            due_date=row["due_date"],
            part_numbers=row["part_numbers"],
            quantities=row["quantities"],
            missing_fields=row["missing_fields"],
            next_action=row["next_action"],
            summary=row["summary"],
            last_message_at=datetime.fromisoformat(row["last_message_at"]),
        )

    def list_cases(self) -> list[QuoteCase]:
        rows = self.conn.execute(
            """
            SELECT thread_id, status, classification, customer_name, customer_email,
                   due_date, part_numbers, quantities, missing_fields, next_action,
                   summary, last_message_at
            FROM cases
            ORDER BY last_message_at DESC
            """
        ).fetchall()
        return [
            QuoteCase(
                thread_id=row["thread_id"],
                status=row["status"],
                classification=row["classification"],
                customer_name=row["customer_name"],
                customer_email=row["customer_email"],
                due_date=row["due_date"],
                part_numbers=row["part_numbers"],
                quantities=row["quantities"],
                missing_fields=row["missing_fields"],
                next_action=row["next_action"],
                summary=row["summary"],
                last_message_at=datetime.fromisoformat(row["last_message_at"]),
            )
            for row in rows
        ]

    def replace_draft(self, draft: Draft) -> None:
        self.conn.execute("DELETE FROM drafts WHERE thread_id = ?", (draft.thread_id,))
        self.conn.execute(
            """
            INSERT INTO drafts (thread_id, draft_type, recipient, subject, body, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                draft.thread_id,
                draft.draft_type,
                draft.recipient,
                draft.subject,
                draft.body,
                draft.status,
            ),
        )
        self.conn.commit()

    def get_draft(self, thread_id: str) -> Draft | None:
        row = self.conn.execute(
            """
            SELECT thread_id, draft_type, recipient, subject, body, status
            FROM drafts
            WHERE thread_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return Draft(
            thread_id=row["thread_id"],
            draft_type=row["draft_type"],
            recipient=row["recipient"],
            subject=row["subject"],
            body=row["body"],
            status=row["status"],
        )

    def list_drafts(self) -> list[Draft]:
        rows = self.conn.execute(
            """
            SELECT thread_id, draft_type, recipient, subject, body, status
            FROM drafts
            ORDER BY id DESC
            """
        ).fetchall()
        return [
            Draft(
                thread_id=row["thread_id"],
                draft_type=row["draft_type"],
                recipient=row["recipient"],
                subject=row["subject"],
                body=row["body"],
                status=row["status"],
            )
            for row in rows
        ]

    def update_draft_status(self, thread_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE drafts SET status = ? WHERE thread_id = ?",
            (status, thread_id),
        )
        self.conn.commit()

    def record_event(self, thread_id: str, event_type: str, payload: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO case_events (thread_id, event_type, payload)
            VALUES (?, ?, ?)
            """,
            (thread_id, event_type, json.dumps(payload, sort_keys=True)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
