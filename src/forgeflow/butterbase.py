"""Butterbase-backed comparison table for the managed agent's host-side tools.

The agent's tools run in this process, not in the sandbox, so the table can live
behind the Data API instead of a SQLite file that dies with a CI runner. That is
the whole point: record_extraction used to append to a list, so every session
opened on an empty table and every round started blind.

IDs are deterministic (an RFQ is its thread, a quote is its supplier within that
thread) because the Data API has no upsert -- deterministic ids turn "write this
supplier's current state" into PATCH-or-POST on a known path.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _base() -> str:
    return (os.environ.get("BUTTERBASE_APP_URL") or "").rstrip("/")


def enabled() -> bool:
    return bool(_base() and os.environ.get("BUTTERBASE_API_KEY"))


def _call(method: str, path: str, payload: Any = None, query: dict | None = None) -> tuple[int, Any]:
    url = f"{_base()}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Authorization": f"Bearer {os.environ['BUTTERBASE_API_KEY']}"}
    if payload is not None:
        # Only when there is a body: the API rejects a bodyless request that
        # still declares application/json, which is every DELETE.
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8").strip()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        return exc.code, body


def _jsonb(value: Any) -> Any:
    """Wrap top-level lists: the Data API rejects a bare array into a jsonb column.

    Objects and scalars pass through, so only the list case pays for this.
    """
    return {"items": value} if isinstance(value, list) else value


def _unjsonb(value: Any) -> Any:
    """Inverse of _jsonb, so callers never see the wrapper."""
    if isinstance(value, dict) and set(value) == {"items"} and isinstance(value["items"], list):
        return value["items"]
    return value


JSONB_COLUMNS = ("extracted", "collection_form", "missing_fields", "next_action", "result")


def _unwrap_row(row: dict) -> dict:
    return {k: (_unjsonb(v) if k in JSONB_COLUMNS else v) for k, v in row.items()}


def _rows(result: Any) -> list[dict]:
    """The Data API returns either a bare list or {"data": [...]}."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("data", "rows", "records"):
            if isinstance(result.get(key), list):
                return result[key]
    return []


def _write(table: str, row_id: str, row: dict, pk: str = "id") -> None:
    """PATCH if it exists, POST if it does not. Stands in for a missing upsert.

    `pk` is not always "id" -- agent_seen and interactions are keyed by
    message_id, and inserting under the wrong column silently nulls the key.
    """
    row = {k: (_jsonb(v) if k in JSONB_COLUMNS else v) for k, v in row.items()}
    status, _ = _call("PATCH", f"/{table}/{urllib.parse.quote(row_id, safe='')}", row)
    if status in (200, 201, 204):
        return
    status, body = _call("POST", f"/{table}", {**row, pk: row_id})
    if status not in (200, 201):
        raise RuntimeError(f"butterbase {table} write failed: HTTP {status}: {body}")


def quote_id(thread_id: str, supplier_email: str) -> str:
    return f"{thread_id}|{supplier_email.lower()}"


def upsert_rfq(thread_id: str, subject: str, buyer_email: str | None,
               status: str, collection_form: Any = None) -> str:
    row = {
        "thread_id": thread_id,
        "subject": subject,
        "buyer_email": buyer_email,
        "status": status,
        "updated_at": "now()",
    }
    if collection_form is not None:
        row["collection_form"] = collection_form
    row = {k: v for k, v in row.items() if v is not None and v != "now()"}
    _write("rfqs", thread_id, row)
    return thread_id


def upsert_supplier_quote(rfq_id: str, thread_id: str, supplier_email: str,
                          supplier_name: str | None, status: str,
                          extracted: Any, latest_message_id: str,
                          missing_fields: Any = None,
                          collection_form: Any = None) -> str:
    qid = quote_id(thread_id, supplier_email)
    row = {
        "rfq_id": rfq_id,
        "thread_id": thread_id,
        "supplier_email": supplier_email,
        "supplier_name": supplier_name,
        "status": status,
        "extracted": extracted,
        "missing_fields": missing_fields,
        "collection_form": collection_form,
        "latest_message_id": latest_message_id,
    }
    _write("supplier_quotes", qid, {k: v for k, v in row.items() if v is not None})
    return qid


def rfq_states(limit: int = 25) -> list[dict[str, Any]]:
    """Same shape store.rfq_states returns, so read_comparison_table is unchanged."""
    _, result = _call("GET", "/rfqs", query={"order": "updated_at.desc", "limit": str(limit)})
    states: list[dict[str, Any]] = []
    for rfq in _rows(result):
        _, quotes = _call(
            "GET", "/supplier_quotes",
            query={"rfq_id": f"eq.{rfq.get('id')}", "order": "updated_at.desc"},
        )
        states.append({
            **_unwrap_row(rfq),
            "supplier_quotes": [_unwrap_row(q) for q in _rows(quotes)],
        })
    return states


def seen_message_ids() -> set[str]:
    _, result = _call("GET", "/agent_seen", query={"select": "message_id", "limit": "1000"})
    return {row["message_id"] for row in _rows(result) if row.get("message_id")}


def mark_seen(message_id: str, session_id: str | None = None, sent_reply: bool = False) -> None:
    _write(
        "agent_seen",
        message_id,
        {"session_id": session_id, "sent_reply": sent_reply},
        pk="message_id",
    )
