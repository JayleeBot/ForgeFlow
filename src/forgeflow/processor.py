from __future__ import annotations

from forgeflow.agent import ProcessingResult, SupplierQuoteData, process_thread
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
                draft = draft_reply(message, result)
                mark_processed(conn, message.message_id, result, draft)
                persist_processing_state(conn, message, result, draft)
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

    missing = _missing_required_items(quote, result)
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


def _norm_tier(tier: str | None) -> str:
    return (tier or "").strip().lower()


def _missing_required_items(quote: SupplierQuoteData, result: ProcessingResult) -> list[str]:
    required = (
        result.rfq_requirements.required_fields
        if result.rfq_requirements
        else ["price_breaks", "lead_time", "payment_terms", "nre"]
    )
    tiers = result.rfq_requirements.requested_tiers if result.rfq_requirements else []
    missing: list[str] = []

    if "price_breaks" in required:
        if tiers:
            for tier in tiers:
                if not any(_norm_tier(row.service_tier) == _norm_tier(tier) for row in quote.price_breaks):
                    missing.append(f"- {tier}: price_breaks")
        elif not quote.price_breaks:
            missing.append("- price_breaks")

    if "lead_time" in required:
        for part in quote.missing_fields.per_part:
            if "lead_time" in part.missing:
                label = f"{part.part_number} ({part.service_tier})" if part.service_tier else part.part_number
                missing.append(f"- {label}: lead_time")
        if tiers:
            for tier in tiers:
                rows = [row for row in quote.price_breaks if _norm_tier(row.service_tier) == _norm_tier(tier)]
                if rows and not any(row.lead_time for row in rows):
                    missing.append(f"- {tier}: lead_time")
        elif quote.price_breaks and not any(row.lead_time for row in quote.price_breaks):
            missing.append("- lead_time")

    quote_level_values = {
        "coo": quote.coo,
        "payment_terms": quote.payment_terms,
        "moq": quote.moq,
        "nre": quote.nre,
    }
    for field in ("coo", "payment_terms", "moq", "nre"):
        if field in required and not quote_level_values[field]:
            missing.append(f"- {field}")

    return list(dict.fromkeys(missing))
