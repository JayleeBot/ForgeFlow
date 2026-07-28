from __future__ import annotations

from forgeflow.agent import ProcessingResult, ResponseAction, decide_response, process_thread
from forgeflow.models import EmailMessage
from forgeflow.store import (
    connect,
    mark_error,
    mark_processed,
    persist_processing_state,
    save_email,
    thread_messages_through,
    unprocessed_messages,
)


def ingest_messages(messages: list[EmailMessage]) -> int:
    with connect() as conn:
        return sum(1 for message in messages if save_email(conn, message))


def process_pending() -> int:
    processed = 0
    with connect() as conn:
        for message in unprocessed_messages(conn):
            try:
                context = thread_messages_through(conn, message.thread_id, message.sent_at)
                result = process_thread(context)
                draft = draft_reply(context, result)
                mark_processed(conn, message.message_id, result, draft)
                persist_processing_state(conn, message, result, draft)
                processed += 1
            except Exception as exc:  # dashboard should show failures instead of hiding them
                mark_error(conn, message.message_id, f"{type(exc).__name__}: {exc}")
    return processed


def respond(messages: list[EmailMessage], result: ProcessingResult) -> ResponseAction:
    """Ask the response agent what to do about this thread."""
    if result.classification not in ("supplier_quote", "supplier_reminder"):
        return ResponseAction(action="none", note="No supplier reply to act on.")
    return decide_response(messages, result)


def render_draft(action: ResponseAction) -> str | None:
    """Flatten the agent's decision into the reply text the store keeps."""
    if action.action == "chase_supplier":
        return "\n".join([f"Subject: {action.subject}", "", action.body or ""])
    if action.action == "flag_buyer":
        return f"[FLAG FOR BUYER]\n\n{action.body or ''}"
    return None


def draft_reply(messages: list[EmailMessage], result: ProcessingResult) -> str | None:
    return render_draft(respond(messages, result))
