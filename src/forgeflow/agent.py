"""LLM-based extraction via the Claude API.

Drop-in replacement for `extractor.extract_case` — same signature, same
`ExtractedCase` contract — so the engine, eval, and metrics are unchanged.
Header-derived fields (supplier name/email) and the derived fields
(missing_fields, summary) reuse the deterministic helpers; the model only does
the hard part: reading messy email content into structured fields.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import anthropic

from forgeflow.extractor import (
    ExtractedCase,
    _build_summary,
    _derive_missing_fields,
    _parse_sender,
)
from forgeflow.models import EmailMessage

MODEL = "claude-opus-4-7"
_PROMPTS_DIR = Path(__file__).parent / "prompts"

_EXTRACTION_TOOL = {
    "name": "record_quote",
    "description": "Record the structured fields extracted from a supplier quote email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["quote_received", "supplier_followup", "ignore"],
            },
            "price_breaks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One per priced line item, as 'QTY@$UNITPRICE' (plain numbers).",
            },
            "production_lead_time": {"type": ["string", "null"]},
            "long_lead_time_parts": {"type": "array", "items": {"type": "string"}},
            "moq": {"type": ["string", "null"]},
            "payment_terms": {"type": ["string", "null"]},
            "nre": {"type": ["string", "null"]},
            "coo": {"type": ["string", "null"]},
        },
        "required": [
            "classification",
            "price_breaks",
            "production_lead_time",
            "long_lead_time_parts",
            "moq",
            "payment_terms",
            "nre",
            "coo",
        ],
    },
}


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    return (_PROMPTS_DIR / "extraction_system.md").read_text(encoding="utf-8")


def extract_case(messages: list[EmailMessage]) -> ExtractedCase:
    latest = messages[-1]
    combined_text = "\n".join(m.body_text for m in messages if m.body_text)
    email_text = f"Subject: {latest.subject}\nFrom: {latest.sender}\n\n{combined_text}"

    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_quote"},
        messages=[{"role": "user", "content": email_text}],
    )

    data = next(block.input for block in response.content if block.type == "tool_use")

    supplier_name, supplier_email = _parse_sender(latest.sender)
    classification = data["classification"]
    price_breaks = data.get("price_breaks") or []
    production_lead_time = data.get("production_lead_time")
    long_lead_time_parts = data.get("long_lead_time_parts") or []
    payment_terms = data.get("payment_terms")
    missing_fields = _derive_missing_fields(
        classification, price_breaks, production_lead_time, payment_terms
    )
    summary = _build_summary(
        classification,
        supplier_name,
        price_breaks,
        production_lead_time,
        long_lead_time_parts,
        data.get("moq"),
        payment_terms,
        data.get("nre"),
        data.get("coo"),
        missing_fields,
    )
    return ExtractedCase(
        classification=classification,
        supplier_name=supplier_name,
        supplier_email=supplier_email,
        price_breaks=price_breaks,
        production_lead_time=production_lead_time,
        long_lead_time_parts=long_lead_time_parts,
        moq=data.get("moq"),
        payment_terms=payment_terms,
        nre=data.get("nre"),
        coo=data.get("coo"),
        missing_fields=missing_fields,
        summary=summary,
    )
