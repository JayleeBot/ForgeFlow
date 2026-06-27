from __future__ import annotations

from forgeflow.agent import ProcessingResult, process_thread
from forgeflow.models import EmailMessage
from forgeflow.store import (
    connect,
    mark_error,
    mark_processed,
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
                mark_processed(conn, message.message_id, result, draft_reply(message, result))
                processed += 1
            except Exception as exc:  # dashboard should show failures instead of hiding them
                mark_error(conn, message.message_id, f"{type(exc).__name__}: {exc}")
    return processed


def draft_reply(message: EmailMessage, result: ProcessingResult) -> str | None:
    quote = result.supplier_quote
    if result.classification not in ("supplier_quote", "supplier_reminder") or quote is None:
        return None
    if quote.blocking_question:
        return f"[FLAG FOR BUYER]\n\nSupplier needs input before ForgeFlow can complete this quote:\n{quote.blocking_question}"

    missing: list[str] = []
    for part in quote.missing_fields.per_part:
        fields = ", ".join(part.missing)
        missing.append(f"- {part.part_number}: {fields}")
    for field in quote.missing_fields.quote_level:
        missing.append(f"- {field}")
    if not missing:
        return None

    return "\n".join([
        f"Subject: Re: {message.subject}",
        "",
        "Hi,",
        "",
        "Thanks for the quote. Could you please confirm the following missing details?",
        *missing,
        "",
        "Best,",
        "ForgeFlow",
    ])
