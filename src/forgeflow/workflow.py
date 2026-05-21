from __future__ import annotations

from forgeflow.extractor import ExtractedCase
from forgeflow.models import Draft, EmailMessage, QuoteCase


def build_case(thread_id: str, messages: list[EmailMessage], extracted: ExtractedCase) -> QuoteCase:
    latest = messages[-1]
    next_action, status = decide_next_action(extracted)
    return QuoteCase(
        thread_id=thread_id,
        status=status,
        classification=extracted.classification,
        supplier_name=extracted.supplier_name,
        supplier_email=extracted.supplier_email,
        price_breaks=", ".join(extracted.price_breaks) or None,
        production_lead_time=extracted.production_lead_time,
        long_lead_time_parts=", ".join(extracted.long_lead_time_parts) or None,
        moq=extracted.moq,
        payment_terms=extracted.payment_terms,
        nre=extracted.nre,
        coo=extracted.coo,
        missing_fields=", ".join(extracted.missing_fields) or None,
        next_action=next_action,
        summary=extracted.summary,
        last_message_at=latest.sent_at,
    )


def decide_next_action(extracted: ExtractedCase) -> tuple[str, str]:
    if extracted.classification == "ignore":
        return "none", "closed"
    if extracted.classification == "supplier_followup":
        return "draft_acknowledgement", "needs_review"
    if extracted.missing_fields:
        return "draft_missing_info_request", "quote_incomplete"
    return "review_complete_quote", "quote_received"


def build_draft(case: QuoteCase, messages: list[EmailMessage]) -> Draft | None:
    if not case.supplier_email or case.next_action == "none":
        return None
    latest_subject = messages[-1].subject

    if case.next_action == "draft_missing_info_request":
        missing = case.missing_fields or "the outstanding details"
        missing_lines = missing.replace(", ", "\n- ")
        body = (
            f"Hi {case.supplier_name or ''},\n\n"
            "Thank you for sending over your quote. We have reviewed it and need a few additional "
            "details before we can move forward with our evaluation:\n\n"
            f"- {missing_lines}\n\n"
            "Could you please provide the above at your earliest convenience? "
            "We want to make sure we are comparing quotes on a like-for-like basis.\n\n"
            "Best regards,\n"
            "Procurement Team"
        )
        return Draft(
            thread_id=case.thread_id,
            draft_type="missing_info_request",
            recipient=case.supplier_email,
            subject=f"Re: {latest_subject}",
            body=body,
            status="draft",
        )

    if case.next_action == "draft_acknowledgement":
        body = (
            f"Hi {case.supplier_name or ''},\n\n"
            "Thank you for following up. We are currently reviewing your quote and will be in touch "
            "shortly with any questions or next steps.\n\n"
            "Best regards,\n"
            "Procurement Team"
        )
        return Draft(
            thread_id=case.thread_id,
            draft_type="acknowledgement",
            recipient=case.supplier_email,
            subject=f"Re: {latest_subject}",
            body=body,
            status="draft",
        )

    return None
