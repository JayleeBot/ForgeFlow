from __future__ import annotations

from forgeflow.extractor import ExtractedCase
from forgeflow.models import Draft, EmailMessage, QuoteCase

_AGENT_FOOTER = (
    "\n\n---\n"
    "Please ensure {agent_email} is included on all replies to this email thread "
    "so our procurement system can track your response."
)


def build_case(
    thread_id: str,
    messages: list[EmailMessage],
    extracted: ExtractedCase,
    buyer_replied: bool = False,
) -> QuoteCase:
    latest = messages[-1]
    next_action, status = decide_next_action(extracted, buyer_replied)
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


def decide_next_action(
    extracted: ExtractedCase,
    buyer_replied: bool = False,
) -> tuple[str, str]:
    if extracted.classification == "ignore":
        return "none", "closed"
    if extracted.classification == "supplier_reminder":
        return "draft_acknowledgement", "needs_review"
    # Supplier asked a blocking question and buyer has not yet replied
    if extracted.missing_fields == ["buyer_input_required"] and not buyer_replied:
        return "flag_buyer", "pending_buyer_input"
    if extracted.missing_fields:
        return "draft_missing_info_request", "quote_incomplete"
    return "review_complete_quote", "quote_received"


def build_draft(
    case: QuoteCase,
    messages: list[EmailMessage],
    agent_email: str = "",
) -> Draft | None:
    if case.next_action == "none":
        return None

    latest_subject = messages[-1].subject if messages else ""
    footer = _AGENT_FOOTER.format(agent_email=agent_email) if agent_email else ""

    # Dashboard-only flag — no email to supplier; notify buyer that input is required
    if case.next_action == "flag_buyer":
        question = ""
        if case.summary and "Question:" in case.summary:
            question = case.summary.split("Question:", 1)[1].strip()
        body = (
            f"Hi,\n\n"
            f"Supplier {case.supplier_name or '(unknown)'} has a question for you that must be "
            f"answered before they can complete the quote.\n\n"
        )
        if question:
            body += f'Their question: "{question}"\n\n'
        body += (
            "Please reply to the supplier directly and CC the agent email so ForgeFlow "
            "can continue tracking this quote once they respond with the complete pricing."
        )
        return Draft(
            thread_id=case.thread_id,
            draft_type="flag_buyer",
            recipient="dashboard",
            subject=f"[Action required] Supplier needs your input — {latest_subject}",
            body=body,
            status="draft",
        )

    if not case.supplier_email:
        return None

    if case.next_action == "draft_missing_info_request":
        missing = case.missing_fields or "the outstanding details"
        missing_lines = missing.replace(", ", "\n- ")
        body = (
            f"Hi {case.supplier_name or ''},\n\n"
            "Thank you for sending over your quote. We have reviewed it and need a few additional "
            "details before we can move forward with our evaluation:\n\n"
            f"- {missing_lines}\n\n"
            "Could you please provide the above at your earliest convenience? "
            "We want to make sure we are comparing quotes on a like-for-like basis."
            + footer
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
            "shortly with any questions or next steps."
            + footer
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
