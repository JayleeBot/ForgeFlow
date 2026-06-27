from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from forgeflow.models import EmailMessage


DB_PATH = Path("data") / "forgeflow.db"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interactions (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipients TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            body_text TEXT NOT NULL,
            source_path TEXT NOT NULL,
            classification TEXT,
            result_json TEXT,
            draft_reply TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT
        )
        """
    )
    conn.commit()


def save_email(conn: sqlite3.Connection, message: EmailMessage) -> bool:
    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO interactions (
            message_id, thread_id, subject, sender, recipients, sent_at, body_text, source_path
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
    conn.commit()
    return conn.total_changes > before


def unprocessed_messages(conn: sqlite3.Connection) -> list[EmailMessage]:
    rows = conn.execute(
        """
        SELECT * FROM interactions
        WHERE classification IS NULL AND error IS NULL
        ORDER BY sent_at ASC
        """
    ).fetchall()
    return [_row_to_message(row) for row in rows]


def thread_messages(conn: sqlite3.Connection, thread_id: str) -> list[EmailMessage]:
    rows = conn.execute(
        "SELECT * FROM interactions WHERE thread_id = ? ORDER BY sent_at ASC",
        (thread_id,),
    ).fetchall()
    return [_row_to_message(row) for row in rows]


def thread_messages_through(
    conn: sqlite3.Connection,
    thread_id: str,
    sent_at: datetime,
) -> list[EmailMessage]:
    rows = conn.execute(
        """
        SELECT * FROM interactions
        WHERE thread_id = ? AND sent_at <= ?
        ORDER BY sent_at ASC
        """,
        (thread_id, sent_at.isoformat()),
    ).fetchall()
    return [_row_to_message(row) for row in rows]


def mark_processed(
    conn: sqlite3.Connection,
    message_id: str,
    result: Any,
    draft_reply: str | None,
) -> None:
    payload = _jsonable(result)
    conn.execute(
        """
        UPDATE interactions
        SET classification = ?, result_json = ?, draft_reply = ?, error = NULL, processed_at = ?
        WHERE message_id = ?
        """,
        (
            payload.get("classification"),
            json.dumps(payload, indent=2, sort_keys=True),
            draft_reply,
            datetime.now().astimezone().isoformat(),
            message_id,
        ),
    )
    conn.commit()


def mark_error(conn: sqlite3.Connection, message_id: str, error: str) -> None:
    conn.execute(
        "UPDATE interactions SET error = ?, processed_at = ? WHERE message_id = ?",
        (error, datetime.now().astimezone().isoformat(), message_id),
    )
    conn.commit()


def recent_interactions(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT message_id, thread_id, subject, sender, sent_at, source_path,
               classification, result_json, draft_reply, error, processed_at
        FROM interactions
        ORDER BY sent_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _row_to_message(row: sqlite3.Row) -> EmailMessage:
    return EmailMessage(
        message_id=row["message_id"],
        thread_id=row["thread_id"],
        subject=row["subject"],
        sender=row["sender"],
        recipients=row["recipients"],
        sent_at=datetime.fromisoformat(row["sent_at"]),
        body_text=row["body_text"],
        source_path=row["source_path"],
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    if data.get("result_json"):
        data["result"] = json.loads(data.pop("result_json"))
    else:
        data["result"] = None
        data.pop("result_json", None)
    return data


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
