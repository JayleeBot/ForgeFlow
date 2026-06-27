"""Three-agent RFQ processing: schema, supplier extraction, and action state."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import anthropic

from forgeflow.models import EmailMessage

Classification = Literal["rfq_sent", "supplier_quote", "supplier_reminder", "ignore"]
MODEL = "claude-opus-4-8"
_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class PriceBreak:
    part_number: str
    quantity: int
    unit_price: str
    lead_time: str | None


@dataclass(slots=True)
class PartMissing:
    part_number: str
    missing: list[str]


@dataclass(slots=True)
class MissingFields:
    per_part: list[PartMissing]
    quote_level: list[str]


@dataclass(slots=True)
class RFQRequirements:
    quantities_requested: list[int]
    required_fields: list[str]


@dataclass(slots=True)
class SupplierQuoteData:
    rfq_reference: str | None
    supplier_name: str | None
    quote_id: str | None
    quote_valid_until: str | None
    incoterms: str | None
    price_breaks: list[PriceBreak]
    long_lead_time_parts: list[str]
    coo: str | None
    payment_terms: str | None
    moq: str | None
    nre: str | None
    blocking_question: str | None
    missing_fields: MissingFields


@dataclass(slots=True)
class ProcessingResult:
    classification: Classification
    rfq_requirements: RFQRequirements | None = None
    supplier_quote: SupplierQuoteData | None = None


# ── Tool schemas ───────────────────────────────────────────────────────────────

_CLASSIFICATION_TOOL = {
    "name": "classify_email",
    "description": "Classify the latest email in an RFQ thread into one of four categories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["rfq_sent", "supplier_quote", "supplier_reminder", "ignore"],
            }
        },
        "required": ["classification"],
    },
}

_RFQ_EXTRACTION_TOOL = {
    "name": "extract_rfq_requirements",
    "description": "Extract what the buyer is requesting in the RFQ email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "quantities_requested": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Quantities the buyer wants price breaks at, e.g. [1000, 2000, 5000].",
            },
            "required_fields": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["price_breaks", "lead_time", "coo", "payment_terms", "moq", "nre"],
                },
                "description": "Fields the buyer explicitly requests. Always include 'price_breaks'. Add others based on explicit mentions.",
            },
        },
        "required": ["quantities_requested", "required_fields"],
    },
}

_QUOTE_EXTRACTION_TOOL = {
    "name": "extract_supplier_quote",
    "description": "Extract the supplier's quote data from the email thread.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rfq_reference": {
                "type": ["string", "null"],
                "description": "Buyer's RFQ reference number this quote answers, verbatim e.g. 'ET-2026-0412'. Null if absent.",
            },
            "supplier_name": {
                "type": ["string", "null"],
                "description": "Supplier company name, verbatim e.g. 'Precision PCB Technology Co., Ltd.'. Null if absent.",
            },
            "quote_id": {
                "type": ["string", "null"],
                "description": "Supplier's own quote number, verbatim e.g. 'PPCB-Q-20260518'. Null if absent.",
            },
            "quote_valid_until": {
                "type": ["string", "null"],
                "description": "Quote validity/expiration date, verbatim e.g. '2026-06-18'. Null if absent.",
            },
            "incoterms": {
                "type": ["string", "null"],
                "description": "Incoterms / delivery terms, verbatim e.g. 'FOB Shenzhen'. Null if absent.",
            },
            "price_breaks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "part_number": {
                            "type": "string",
                            "description": "Part number this row is priced for, e.g. 'ET-PCBA-MAIN-V2'.",
                        },
                        "quantity": {"type": "integer"},
                        "unit_price": {"type": "string"},
                        "lead_time": {
                            "type": ["string", "null"],
                            "description": "Production lead time for this part, verbatim e.g. '15 business days'. Null if this part has no stated lead time.",
                        },
                    },
                    "required": ["part_number", "quantity", "unit_price", "lead_time"],
                },
                "description": "One row per quantity tier. part_number and lead_time repeat across a part's tiers.",
            },
            "long_lead_time_parts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Parts with lead time >= 8 calendar weeks, e.g. ['IC-TPS65987DDFT (32 WEEKS)']. Business days are not calendar weeks. Empty array if none.",
            },
            "coo": {
                "type": ["string", "null"],
                "description": "Country of origin verbatim, e.g. 'China'. Null if absent.",
            },
            "payment_terms": {
                "type": ["string", "null"],
                "description": "Payment terms verbatim, e.g. 'Net 30'. Null if absent or TBD.",
            },
            "moq": {
                "type": ["string", "null"],
                "description": "Minimum order quantity if stated. Null if absent.",
            },
            "nre": {
                "type": ["string", "null"],
                "description": "Non-recurring engineering cost, including any one-time tooling or setup fee, if stated. Null if absent or TBD.",
            },
            "blocking_question": {
                "type": ["string", "null"],
                "description": "A question the supplier asked that the buyer must answer before the quote can be finalized. Null if no such question.",
            },
            "missing_fields": {
                "type": "object",
                "properties": {
                    "per_part": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "part_number": {"type": "string"},
                                "missing": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": ["unit_price", "lead_time"],
                                    },
                                },
                            },
                            "required": ["part_number", "missing"],
                        },
                        "description": "Per-part line-level gaps for every quoted part that is incomplete (include parts mentioned but not yet priced).",
                    },
                    "quote_level": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["payment_terms", "nre"],
                        },
                        "description": "Quote-wide fields not yet provided.",
                    },
                },
                "required": ["per_part", "quote_level"],
            },
        },
        "required": [
            "rfq_reference", "supplier_name", "quote_id", "quote_valid_until", "incoterms",
            "price_breaks", "long_lead_time_parts",
            "coo", "payment_terms", "moq", "nre",
            "blocking_question", "missing_fields",
        ],
    },
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _format_thread(messages: list[EmailMessage]) -> str:
    parts: list[str] = []
    for idx, message in enumerate(messages, start=1):
        tag = "latest_email" if idx == len(messages) else "thread_context_email"
        index_attr = f' index="{idx}"' if tag == "thread_context_email" else ""
        parts.append(
            "\n".join([
                f"<{tag}{index_attr}>",
                f"Subject: {message.subject}",
                f"From: {message.sender}",
                f"To: {message.recipients}",
                "Body:",
                message.body_text or "",
                f"</{tag}>",
            ])
        )
    return "\n\n".join(parts)


def _system(prompt_file: str) -> list[dict]:
    text = (_PROMPTS_DIR / prompt_file).read_text(encoding="utf-8")
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


# ── Step 1: Classification ─────────────────────────────────────────────────────

def _classify(messages: list[EmailMessage]) -> str:
    response = _client().messages.create(
        model=MODEL,
        max_tokens=256,
        system=_system("classification_router.txt"),
        tools=[_CLASSIFICATION_TOOL],
        tool_choice={"type": "tool", "name": "classify_email"},
        messages=[{"role": "user", "content": _format_thread(messages)}],
    )
    data = next(block.input for block in response.content if block.type == "tool_use")
    return data["classification"]


# ── Agent 1: RFQ Schema Agent ─────────────────────────────────────────────────

def _extract_rfq_requirements(messages: list[EmailMessage]) -> RFQRequirements:
    response = _client().messages.create(
        model=MODEL,
        max_tokens=512,
        system=_system("rfq_extraction.txt"),
        tools=[_RFQ_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "extract_rfq_requirements"},
        messages=[{"role": "user", "content": _format_thread(messages)}],
    )
    data = next(block.input for block in response.content if block.type == "tool_use")
    return RFQRequirements(
        quantities_requested=data["quantities_requested"],
        required_fields=data["required_fields"],
    )


# ── Agent 2: Supplier Extraction Agent ────────────────────────────────────────

def _extract_supplier_quote(messages: list[EmailMessage]) -> SupplierQuoteData:
    response = _client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_system("quote_extraction.txt"),
        tools=[_QUOTE_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "extract_supplier_quote"},
        messages=[{"role": "user", "content": _format_thread(messages)}],
    )
    data = next(block.input for block in response.content if block.type == "tool_use")
    return SupplierQuoteData(
        rfq_reference=data["rfq_reference"],
        supplier_name=data["supplier_name"],
        quote_id=data["quote_id"],
        quote_valid_until=data["quote_valid_until"],
        incoterms=data["incoterms"],
        price_breaks=[
            PriceBreak(pb["part_number"], pb["quantity"], pb["unit_price"], pb["lead_time"])
            for pb in data["price_breaks"]
        ],
        long_lead_time_parts=data["long_lead_time_parts"],
        coo=data["coo"],
        payment_terms=data["payment_terms"],
        moq=data["moq"],
        nre=data["nre"],
        blocking_question=data["blocking_question"],
        missing_fields=MissingFields(
            per_part=[
                PartMissing(pm["part_number"], pm["missing"])
                for pm in data["missing_fields"]["per_part"]
            ],
            quote_level=data["missing_fields"]["quote_level"],
        ),
    )


# ── Router entry point ─────────────────────────────────────────────────────────

def process_thread(messages: list[EmailMessage]) -> ProcessingResult:
    if not messages:
        raise ValueError("Cannot process an empty email thread")

    classification = _classify(messages)

    if classification == "rfq_sent":
        return ProcessingResult(
            classification=classification,
            rfq_requirements=_extract_rfq_requirements(messages),
        )
    elif classification in ("supplier_quote", "supplier_reminder"):
        return ProcessingResult(
            classification=classification,
            rfq_requirements=_extract_rfq_requirements(messages),
            supplier_quote=_extract_supplier_quote(messages),
        )
    else:  # ignore
        return ProcessingResult(classification=classification)
