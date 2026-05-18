from __future__ import annotations

import re
from dataclasses import dataclass

from forgeflow.models import EmailMessage


DUE_DATE_RE = re.compile(
    r"\b(?:due|needed by|need by|deadline)\s*[:\-]?\s*([A-Z][a-z]{2,8}\s+\d{1,2}(?:,\s*\d{4})?)",
    re.IGNORECASE,
)
PART_RE = re.compile(r"\b(?:part|pn|p\/n|item)\s*[:#\-]?\s*([A-Z0-9\-]{3,})", re.IGNORECASE)
QTY_RE = re.compile(r"\b(?:qty|quantity)\s*[:\-]?\s*(\d+)", re.IGNORECASE)
RFQ_HINTS = ("rfq", "request for quote", "quote request", "please quote", "quotation")
FOLLOWUP_HINTS = ("following up", "checking in", "any update", "status on quote")


@dataclass(slots=True)
class ExtractedCase:
    classification: str
    customer_name: str | None
    customer_email: str | None
    due_date: str | None
    part_numbers: list[str]
    quantities: list[str]
    missing_fields: list[str]
    summary: str


def extract_case(messages: list[EmailMessage]) -> ExtractedCase:
    latest = messages[-1]
    combined_text = "\n".join(message.body_text for message in messages if message.body_text)
    combined_lower = f"{latest.subject}\n{combined_text}".lower()
    classification = _classify(combined_lower)
    customer_name, customer_email = _parse_sender(latest.sender)
    due_date = _find_first(DUE_DATE_RE, combined_text)
    part_numbers = _find_all(PART_RE, combined_text)
    quantities = _find_all(QTY_RE, combined_text)
    missing_fields = _derive_missing_fields(classification, due_date, part_numbers, quantities)
    summary = _build_summary(classification, customer_name, due_date, part_numbers, quantities, missing_fields)
    return ExtractedCase(
        classification=classification,
        customer_name=customer_name,
        customer_email=customer_email,
        due_date=due_date,
        part_numbers=part_numbers,
        quantities=quantities,
        missing_fields=missing_fields,
        summary=summary,
    )


def _classify(text: str) -> str:
    if any(hint in text for hint in FOLLOWUP_HINTS):
        return "customer_followup"
    if any(hint in text for hint in RFQ_HINTS):
        return "new_rfq"
    if "?" in text or "clarify" in text or "clarification" in text:
        return "clarification_needed"
    return "ignore"


def _parse_sender(sender: str) -> tuple[str | None, str | None]:
    match = re.match(r'(?:"?([^"<]+)"?\s*)?<([^>]+)>', sender)
    if match:
        name = match.group(1).strip() if match.group(1) else None
        email = match.group(2).strip()
        return name, email
    return None, sender.strip() if "@" in sender else None


def _find_first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _find_all(pattern: re.Pattern[str], text: str) -> list[str]:
    values = [match.strip() for match in pattern.findall(text)]
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.lower()
        if normalized in seen:
            continue
        deduped.append(value)
        seen.add(normalized)
    return deduped


def _derive_missing_fields(
    classification: str,
    due_date: str | None,
    part_numbers: list[str],
    quantities: list[str],
) -> list[str]:
    if classification == "ignore":
        return []
    missing: list[str] = []
    if not due_date:
        missing.append("due_date")
    if not part_numbers:
        missing.append("part_numbers")
    if not quantities:
        missing.append("quantities")
    return missing


def _build_summary(
    classification: str,
    customer_name: str | None,
    due_date: str | None,
    part_numbers: list[str],
    quantities: list[str],
    missing_fields: list[str],
) -> str:
    customer = customer_name or "Unknown customer"
    due = due_date or "no due date provided"
    parts = ", ".join(part_numbers) if part_numbers else "no part numbers found"
    qtys = ", ".join(quantities) if quantities else "no quantities found"
    missing = ", ".join(missing_fields) if missing_fields else "none"
    return (
        f"{classification} from {customer}; due {due}; "
        f"parts: {parts}; quantities: {qtys}; missing: {missing}"
    )
