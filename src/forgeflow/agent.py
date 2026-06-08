"""Classification router agent for RFQ email threads."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import anthropic

from forgeflow.models import EmailMessage

Classification = Literal["quote_received", "supplier_reminder", "ignore"]
MODEL = "claude-opus-4-7"
_PROMPTS_DIR = Path(__file__).parent / "prompts"

_CLASSIFICATION_TOOL = {
    "name": "classify_email",
    "description": "Classify an RFQ email thread and identify quote-completeness signals.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["quote_received", "supplier_reminder", "ignore"],
            },
            "has_price_breaks": {"type": "boolean"},
            "has_production_lead_time": {"type": "boolean"},
            "has_long_lead_time_parts": {"type": "boolean"},
            "has_payment_terms": {"type": "boolean"},
            "missing_fields": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "production_lead_time",
                        "payment_terms",
                        "buyer_input_required",
                    ],
                },
            },
        },
        "required": [
            "classification",
            "has_price_breaks",
            "has_production_lead_time",
            "has_long_lead_time_parts",
            "has_payment_terms",
            "missing_fields",
        ],
    },
}


@dataclass(slots=True)
class ClassificationResult:
    classification: Classification
    has_price_breaks: bool
    has_production_lead_time: bool
    has_long_lead_time_parts: bool
    has_payment_terms: bool
    missing_fields: list[str]


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    return (_PROMPTS_DIR / "classification_router.txt").read_text(encoding="utf-8")


def _format_thread(messages: list[EmailMessage]) -> str:
    parts: list[str] = []
    for idx, message in enumerate(messages, start=1):
        tag = "latest_email" if idx == len(messages) else "thread_context_email"
        index_attr = f' index="{idx}"' if tag == "thread_context_email" else ""
        parts.append(
            "\n".join(
                [
                    f"<{tag}{index_attr}>",
                    f"Subject: {message.subject}",
                    f"From: {message.sender}",
                    f"To: {message.recipients}",
                    "Body:",
                    message.body_text or "",
                    f"</{tag}>",
                ]
            )
        )
    return "\n\n".join(parts)


def classify_thread(messages: list[EmailMessage]) -> ClassificationResult:
    if not messages:
        raise ValueError("Cannot classify an empty email thread")

    response = _client().messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_CLASSIFICATION_TOOL],
        tool_choice={"type": "tool", "name": "classify_email"},
        messages=[{"role": "user", "content": _format_thread(messages)}],
    )
    data = next(block.input for block in response.content if block.type == "tool_use")
    return ClassificationResult(
        classification=data["classification"],
        has_price_breaks=data["has_price_breaks"],
        has_production_lead_time=data["has_production_lead_time"],
        has_long_lead_time_parts=data["has_long_lead_time_parts"],
        has_payment_terms=data["has_payment_terms"],
        missing_fields=data["missing_fields"],
    )
