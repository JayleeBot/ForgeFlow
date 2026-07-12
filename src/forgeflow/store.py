from __future__ import annotations

import json
import sqlite3
import hashlib
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
            processed_at TEXT,
            reply_sent_at TEXT,
            rfq_id TEXT,
            supplier_quote_id TEXT
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(interactions)").fetchall()}
    if "reply_sent_at" not in columns:
        conn.execute("ALTER TABLE interactions ADD COLUMN reply_sent_at TEXT")
    if "rfq_id" not in columns:
        conn.execute("ALTER TABLE interactions ADD COLUMN rfq_id TEXT")
    if "supplier_quote_id" not in columns:
        conn.execute("ALTER TABLE interactions ADD COLUMN supplier_quote_id TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rfqs (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL UNIQUE,
            subject TEXT NOT NULL,
            buyer_email TEXT,
            status TEXT NOT NULL,
            schema_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier_quotes (
            id TEXT PRIMARY KEY,
            rfq_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            supplier_email TEXT NOT NULL,
            supplier_name TEXT,
            status TEXT NOT NULL,
            extracted_json TEXT,
            collection_form_json TEXT,
            missing_fields_json TEXT,
            next_action_json TEXT,
            latest_message_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (rfq_id) REFERENCES rfqs(id)
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


def persist_processing_state(
    conn: sqlite3.Connection,
    message: EmailMessage,
    result: Any,
    draft_reply: str | None,
) -> None:
    payload = _jsonable(result)
    now = datetime.now().astimezone().isoformat()

    if payload.get("rfq_requirements"):
        rfq_id = _rfq_id(message.thread_id)
        schema = _collection_form(payload)
        conn.execute(
            """
            INSERT INTO rfqs (id, thread_id, subject, buyer_email, status, schema_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                subject = excluded.subject,
                buyer_email = excluded.buyer_email,
                status = excluded.status,
                schema_json = excluded.schema_json,
                updated_at = excluded.updated_at
            """,
            (
                rfq_id,
                message.thread_id,
                message.subject,
                message.sender,
                "collecting",
                json.dumps(schema, indent=2, sort_keys=True),
                now,
            ),
        )
        conn.execute(
            "UPDATE interactions SET rfq_id = ? WHERE message_id = ?",
            (rfq_id, message.message_id),
        )
        conn.commit()
        return

    quote = payload.get("supplier_quote")
    if not quote:
        conn.commit()
        return

    rfq_id, rfq_requirements = _ensure_rfq_for_thread(conn, message, now)
    supplier_quote_id = _supplier_quote_id(message.thread_id, message.sender)
    collection_form = _collection_form(payload, rfq_requirements)
    next_action = _next_action(collection_form, draft_reply)
    status = next_action["status"]
    conn.execute(
        """
        INSERT INTO supplier_quotes (
            id, rfq_id, thread_id, supplier_email, supplier_name, status, extracted_json,
            collection_form_json, missing_fields_json, next_action_json, latest_message_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            supplier_name = excluded.supplier_name,
            status = excluded.status,
            extracted_json = excluded.extracted_json,
            collection_form_json = excluded.collection_form_json,
            missing_fields_json = excluded.missing_fields_json,
            next_action_json = excluded.next_action_json,
            latest_message_id = excluded.latest_message_id,
            updated_at = excluded.updated_at
        """,
        (
            supplier_quote_id,
            rfq_id,
            message.thread_id,
            message.sender,
            quote.get("supplier_name"),
            status,
            json.dumps(quote, indent=2, sort_keys=True),
            json.dumps(collection_form, indent=2, sort_keys=True),
            json.dumps(collection_form.get("missing_items", []), indent=2, sort_keys=True)
            if collection_form
            else "[]",
            json.dumps(next_action, indent=2, sort_keys=True),
            message.message_id,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE interactions
        SET rfq_id = ?, supplier_quote_id = ?
        WHERE message_id = ?
        """,
        (rfq_id, supplier_quote_id, message.message_id),
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
               classification, result_json, draft_reply, error, processed_at, reply_sent_at,
               rfq_id, supplier_quote_id
        FROM interactions
        ORDER BY sent_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    thread_requirements = _thread_requirements(conn)
    return [_row_to_dict(row, thread_requirements.get(row["thread_id"])) for row in rows]


def rebuild_state_from_interactions(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT *
        FROM interactions
        WHERE result_json IS NOT NULL
        ORDER BY sent_at ASC
        """
    ).fetchall()
    rebuilt = 0
    for row in rows:
        result = json.loads(row["result_json"])
        persist_processing_state(
            conn,
            _row_to_message(row),
            result,
            row["draft_reply"],
        )
        rebuilt += 1
    return rebuilt


def rfq_states(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rfq_rows = conn.execute(
        "SELECT * FROM rfqs ORDER BY updated_at DESC"
    ).fetchall()
    results: list[dict[str, Any]] = []
    for rfq in rfq_rows:
        quote_rows = conn.execute(
            "SELECT * FROM supplier_quotes WHERE rfq_id = ? ORDER BY updated_at DESC",
            (rfq["id"],),
        ).fetchall()
        data = dict(rfq)
        data["schema"] = json.loads(data.pop("schema_json")) if data.get("schema_json") else None
        data["supplier_quotes"] = [_supplier_quote_row_to_dict(row) for row in quote_rows]
        results.append(data)
    return results


def unsent_draft_replies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT message_id, subject, sender, draft_reply
        FROM interactions
        WHERE draft_reply IS NOT NULL AND reply_sent_at IS NULL
        ORDER BY sent_at ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def draft_reply_for_message(conn: sqlite3.Connection, message_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT message_id, subject, sender, draft_reply, reply_sent_at
        FROM interactions
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    return dict(row) if row else None


def mark_reply_sent(conn: sqlite3.Connection, message_id: str) -> None:
    conn.execute(
        "UPDATE interactions SET reply_sent_at = ? WHERE message_id = ?",
        (datetime.now().astimezone().isoformat(), message_id),
    )
    conn.commit()


def _supplier_quote_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("extracted_json", "collection_form_json", "missing_fields_json", "next_action_json"):
        data[key.removesuffix("_json")] = json.loads(data.pop(key)) if data.get(key) else None
    return data


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


def _row_to_dict(
    row: sqlite3.Row,
    rfq_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(row)
    if data.get("result_json"):
        data["result"] = json.loads(data.pop("result_json"))
    else:
        data["result"] = None
        data.pop("result_json", None)
    data["collection_form"] = _collection_form(data["result"], rfq_requirements)
    return data


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _thread_requirements(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT thread_id, result_json
        FROM interactions
        WHERE result_json IS NOT NULL
        ORDER BY sent_at ASC
        """
    ).fetchall()
    requirements: dict[str, dict[str, Any]] = {}
    for row in rows:
        result = json.loads(row["result_json"])
        if result.get("rfq_requirements"):
            requirements[row["thread_id"]] = result["rfq_requirements"]
    return requirements


def _collection_form(
    result: dict[str, Any] | None,
    rfq_requirements: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not result:
        return None
    if result.get("rfq_requirements") and not result.get("supplier_quote"):
        requirements = result["rfq_requirements"]
        return {
            "type": "rfq_requirements",
            "schema_source": "buyer_rfq",
            "status": "form_created",
            "fields_to_collect": [
                {"key": field, "required": True, "value": None, "status": "pending"}
                for field in requirements.get("required_fields", [])
            ],
            "quantities_requested": requirements.get("quantities_requested", []),
            "requested_tiers": requirements.get("requested_tiers", []),
            "our_part_number": requirements.get("our_part_number"),
            "manufacturer": requirements.get("manufacturer"),
            "mfg_part_number": requirements.get("mfg_part_number"),
        }

    quote = result.get("supplier_quote")
    if not quote:
        return None

    fields = _quote_fields(quote, rfq_requirements)
    schema_source = "buyer_rfq" if rfq_requirements else "inferred_from_quote"
    return {
        "type": "supplier_quote_collection",
        "schema_source": schema_source,
        "status": "complete" if _quote_complete(quote, rfq_requirements) else "needs_followup",
        "quantities_requested": (rfq_requirements or {}).get("quantities_requested", []),
        "fields": fields,
        "price_breaks": quote.get("price_breaks", []),
        "missing_items": _missing_items(quote, rfq_requirements),
        "manufacturer": quote.get("manufacturer"),
        "mfg_part_number": quote.get("mfg_part_number"),
        "expected_mfg_part_number": (rfq_requirements or {}).get("mfg_part_number"),
        "flags": {
            "blocking_question": quote.get("blocking_question"),
            "long_lead_time_parts": quote.get("long_lead_time_parts", []),
            "mfg_mismatch": _mfg_mismatch(quote, rfq_requirements),
        },
    }


def _ensure_rfq_for_thread(
    conn: sqlite3.Connection,
    message: EmailMessage,
    now: str,
) -> tuple[str, dict[str, Any] | None]:
    rfq_id = _rfq_id(message.thread_id)
    row = conn.execute(
        "SELECT schema_json FROM rfqs WHERE thread_id = ?",
        (message.thread_id,),
    ).fetchone()
    if row:
        schema = json.loads(row["schema_json"]) if row["schema_json"] else None
        return rfq_id, _requirements_from_schema(schema)

    conn.execute(
        """
        INSERT INTO rfqs (id, thread_id, subject, buyer_email, status, schema_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rfq_id,
            message.thread_id,
            message.subject,
            None,
            "collecting",
            None,
            now,
        ),
    )
    return rfq_id, None


def _requirements_from_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not schema:
        return None
    return {
        "required_fields": [
            field["key"]
            for field in schema.get("fields_to_collect", [])
            if field.get("required")
        ],
        "quantities_requested": schema.get("quantities_requested", []),
        "requested_tiers": schema.get("requested_tiers", []),
        "our_part_number": schema.get("our_part_number"),
        "manufacturer": schema.get("manufacturer"),
        "mfg_part_number": schema.get("mfg_part_number"),
    }


def _next_action(collection_form: dict[str, Any] | None, draft_reply: str | None) -> dict[str, Any]:
    if not collection_form:
        return {"status": "ignore", "type": "none"}
    flags = collection_form.get("flags", {})
    if flags.get("blocking_question"):
        return {
            "status": "needs_buyer_input",
            "type": "flag_buyer",
            "body": flags["blocking_question"],
        }
    if flags.get("mfg_mismatch"):
        return {
            "status": "needs_buyer_input",
            "type": "flag_buyer",
            "body": draft_reply,
        }
    if collection_form.get("missing_items"):
        return {
            "status": "needs_followup",
            "type": "draft_supplier_reply",
            "body": draft_reply,
        }
    return {"status": "ready_for_review", "type": "mark_complete"}


def _rfq_id(thread_id: str) -> str:
    return f"rfq_{thread_id}"


def _supplier_quote_id(thread_id: str, sender: str) -> str:
    digest = hashlib.sha1(f"{thread_id}|{sender}".encode("utf-8")).hexdigest()[:16]
    return f"quote_{digest}"


def _quote_fields(
    quote: dict[str, Any],
    rfq_requirements: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    missing = set(quote.get("missing_fields", {}).get("quote_level", []))
    requested = (rfq_requirements or {}).get("required_fields") or _inferred_field_keys(quote)
    field_defs = {
        "price_breaks": ("Price Breaks", quote.get("price_breaks", [])),
        "lead_time": ("Lead Time", _lead_time_value(quote)),
        "coo": ("COO", quote.get("coo")),
        "payment_terms": ("Payment Terms", quote.get("payment_terms")),
        "moq": ("MOQ", quote.get("moq")),
        "nre": ("NRE", quote.get("nre")),
    }
    fields = [
        {
            "key": "supplier_name",
            "label": "Supplier",
            "required": False,
            "value": quote.get("supplier_name"),
            "status": "filled" if quote.get("supplier_name") else "not_provided",
        },
        {
            "key": "rfq_reference",
            "label": "RFQ Reference",
            "required": False,
            "value": quote.get("rfq_reference"),
            "status": "filled" if quote.get("rfq_reference") else "not_provided",
        },
    ]
    for key in requested:
        label, value = field_defs.get(key, (key.replace("_", " ").title(), quote.get(key)))
        filled = bool(value)
        fields.append(
            {
                "key": key,
                "label": label,
                "required": True,
                "value": value,
                "status": "filled" if filled else ("missing" if key in missing or key == "price_breaks" else "not_provided"),
            }
        )
    return fields


def _inferred_field_keys(quote: dict[str, Any]) -> list[str]:
    keys = ["price_breaks", "lead_time"]
    for key in ("coo", "payment_terms", "moq", "nre"):
        if quote.get(key) or key in quote.get("missing_fields", {}).get("quote_level", []):
            keys.append(key)
    return keys


def _lead_time_value(quote: dict[str, Any]) -> str | None:
    values = [
        row.get("lead_time")
        for row in quote.get("price_breaks", [])
        if row.get("lead_time")
    ]
    if not values:
        return None
    unique = list(dict.fromkeys(values))
    return ", ".join(unique)


def _quote_complete(quote: dict[str, Any], rfq_requirements: dict[str, Any] | None = None) -> bool:
    missing_fields = quote.get("missing_fields", {})
    return (
        not quote.get("blocking_question")
        and not _mfg_mismatch(quote, rfq_requirements)
        and not missing_fields.get("quote_level")
        and not missing_fields.get("per_part")
        and not _missing_required_items(quote, rfq_requirements)
    )


def _missing_items(quote: dict[str, Any], rfq_requirements: dict[str, Any] | None = None) -> list[str]:
    missing_fields = quote.get("missing_fields", {})
    items = list(_missing_required_items(quote, rfq_requirements))
    for item in missing_fields.get("quote_level", []):
        if item not in items:
            items.append(item)
    for part in missing_fields.get("per_part", []):
        item = f"{part.get('part_number')}: {', '.join(part.get('missing', []))}"
        if item not in items:
            items.append(item)
    return items


def _norm(tier: str | None) -> str:
    return (tier or "").strip().lower()


def _missing_required_items(
    quote: dict[str, Any],
    rfq_requirements: dict[str, Any] | None,
) -> list[str]:
    required = (rfq_requirements or {}).get("required_fields") or _inferred_field_keys(quote)
    tiers = (rfq_requirements or {}).get("requested_tiers") or []
    items: list[str] = []
    price_breaks = quote.get("price_breaks", [])

    if "price_breaks" in required:
        if tiers:
            for tier in tiers:
                if not any(_norm(row.get("service_tier")) == _norm(tier) for row in price_breaks):
                    items.append(f"{tier}: price_breaks")
        elif not price_breaks:
            items.append("price_breaks")

    if "lead_time" in required:
        for part in quote.get("missing_fields", {}).get("per_part", []):
            if "lead_time" in part.get("missing", []):
                tier = part.get("service_tier")
                label = f"{part.get('part_number')} ({tier})" if tier else part.get("part_number")
                items.append(f"{label}: lead_time")
        if tiers:
            for tier in tiers:
                rows = [row for row in price_breaks if _norm(row.get("service_tier")) == _norm(tier)]
                if rows and not any(row.get("lead_time") for row in rows):
                    items.append(f"{tier}: lead_time")
        elif price_breaks and not any(row.get("lead_time") for row in price_breaks):
            items.append("lead_time")

    quote_level_values = {
        "coo": quote.get("coo"),
        "payment_terms": quote.get("payment_terms"),
        "moq": quote.get("moq"),
        "nre": quote.get("nre"),
    }
    for field in ("coo", "payment_terms", "moq", "nre"):
        if field in required and not quote_level_values[field]:
            items.append(field)

    # MFG part number is presence-driven: required only when the buyer named one.
    buyer_mfg = (rfq_requirements or {}).get("mfg_part_number")
    if buyer_mfg and not quote.get("mfg_part_number"):
        items.append("mfg_part_number")

    return list(dict.fromkeys(items))


def _mfg_mismatch(quote: dict[str, Any], rfq_requirements: dict[str, Any] | None) -> dict[str, str] | None:
    """Return {expected, quoted} when the buyer named an MFG part number and the
    supplier quoted a different one — a substitution the buyer must review."""
    expected = (rfq_requirements or {}).get("mfg_part_number")
    quoted = quote.get("mfg_part_number")
    if expected and quoted and _norm(expected) != _norm(quoted):
        return {"expected": expected, "quoted": quoted}
    return None
