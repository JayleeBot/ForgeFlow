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
        customer_name=extracted.customer_name,
        customer_email=extracted.customer_email,
        due_date=extracted.due_date,
        part_numbers=", ".join(extracted.part_numbers) or None,
        quantities=", ".join(extracted.quantities) or None,
        missing_fields=", ".join(extracted.missing_fields) or None,
        next_action=next_action,
        summary=extracted.summary,
        last_message_at=latest.sent_at,
    )


def decide_next_action(extracted: ExtractedCase) -> tuple[str, str]:
    if extracted.classification == "ignore":
        return "none", "closed"
    if extracted.missing_fields:
        return "draft_clarification", "needs_info"
    if extracted.classification == "customer_followup":
        return "draft_status_reply", "needs_review"
    return "schedule_followup", "waiting_on_quote"


def build_draft(case: QuoteCase, messages: list[EmailMessage]) -> Draft | None:
    if not case.customer_email or case.next_action == "none":
        return None
    latest_subject = messages[-1].subject
    if case.next_action == "draft_clarification":
        missing = case.missing_fields or "details"
        body = (
            f"Hi {case.customer_name or ''},\n\n"
            "Thanks for the quote request. Before we can proceed, could you confirm the following:\n"
            f"- {missing.replace(', ', chr(10) + '- ')}\n\n"
            "Once we have that information, we can move this forward.\n\n"
            "Best,\nForgeFlow Assistant"
        )
        return Draft(
            thread_id=case.thread_id,
            draft_type="clarification",
            recipient=case.customer_email,
            subject=f"Re: {latest_subject}",
            body=body,
            status="draft",
        )
    if case.next_action == "draft_status_reply":
        body = (
            f"Hi {case.customer_name or ''},\n\n"
            "Thanks for following up. We are reviewing your request and will share an update shortly.\n\n"
            "Best,\nForgeFlow Assistant"
        )
        return Draft(
            thread_id=case.thread_id,
            draft_type="status_reply",
            recipient=case.customer_email,
            subject=f"Re: {latest_subject}",
            body=body,
            status="draft",
        )
    if case.next_action == "schedule_followup":
        body = (
            f"Hi {case.customer_name or ''},\n\n"
            "Following up on your quote request. We are reviewing the details and will keep you posted if we need anything else.\n\n"
            "Best,\nForgeFlow Assistant"
        )
        return Draft(
            thread_id=case.thread_id,
            draft_type="followup",
            recipient=case.customer_email,
            subject=f"Re: {latest_subject}",
            body=body,
            status="draft",
        )
    return None
