"""Three-agent RFQ processing: schema, supplier extraction, and action state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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
    service_tier: str | None = None


@dataclass(slots=True)
class PartMissing:
    part_number: str
    missing: list[str]
    service_tier: str | None = None


@dataclass(slots=True)
class MissingFields:
    per_part: list[PartMissing]
    quote_level: list[str]


@dataclass(slots=True)
class RFQRequirements:
    quantities_requested: list[int]
    required_fields: list[str]
    requested_tiers: list[str]
    our_part_number: str | None = None
    manufacturer: str | None = None
    mfg_part_number: str | None = None


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
    manufacturer: str | None = None
    mfg_part_number: str | None = None


@dataclass(slots=True)
class ResponseAction:
    """What the response agent decided, and the copy it wrote."""
    action: Literal["none", "chase_supplier", "flag_buyer", "ready_for_review"]
    fields_requested: list[str] = field(default_factory=list)
    subject: str | None = None
    body: str | None = None
    reason: str | None = None
    note: str | None = None


@dataclass(slots=True)
class ProcessingResult:
    classification: Classification
    rfq_requirements: RFQRequirements | None = None
    supplier_quote: SupplierQuoteData | None = None


# ── Tool schemas ───────────────────────────────────────────────────────────────

_RFQ_REQUIREMENTS_SCHEMA = {
    "type": ["object", "null"],
    "description": (
        "The collection form for this RFQ — what supplier replies must eventually provide. "
        "Fill for every classification except 'ignore'. Null for 'ignore'."
    ),
    "properties": {
        "quantities_requested": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Quantities the buyer wants priced, e.g. [1000, 2000, 5000].",
        },
        "required_fields": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["price_breaks", "lead_time", "coo", "payment_terms", "moq", "nre"],
            },
            "description": "Fields the buyer explicitly requests. Always include 'price_breaks'.",
        },
        "requested_tiers": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Verbatim service-tier labels the buyer asks to compare, e.g. ['Quick Turn', "
                "'Standard Turn']. Empty when the buyer names no split — never invent tiers."
            ),
        },
        "our_part_number": {
            "type": ["string", "null"],
            "description": "The buyer's own internal part number, verbatim. Null if none given.",
        },
        "manufacturer": {
            "type": ["string", "null"],
            "description": "Manufacturer / AVL brand named by the buyer, verbatim. Null for custom parts.",
        },
        "mfg_part_number": {
            "type": ["string", "null"],
            "description": (
                "The manufacturer part number named by the buyer, verbatim. Record ONLY when "
                "genuinely distinct from our_part_number — a single part number with no separate "
                "manufacturer number is our_part_number, and this stays null."
            ),
        },
    },
    "required": ["quantities_requested", "required_fields", "requested_tiers",
                 "our_part_number", "manufacturer", "mfg_part_number"],
}

_SUPPLIER_QUOTE_SCHEMA = {
    "type": ["object", "null"],
    "description": (
        "The supplier's commercial data, extracted across the whole thread. Fill for "
        "'supplier_quote' and 'supplier_reminder'; null otherwise."
    ),
    "properties": {
        "rfq_reference": {"type": ["string", "null"], "description": "Buyer's RFQ reference, verbatim. Null if absent."},
        "supplier_name": {"type": ["string", "null"], "description": "Supplier company name, verbatim. Null if absent."},
        "quote_id": {"type": ["string", "null"], "description": "Supplier's own quote number, verbatim. Null if absent."},
        "quote_valid_until": {"type": ["string", "null"], "description": "Validity / expiry date, verbatim. Null if absent."},
        "incoterms": {"type": ["string", "null"], "description": "Delivery terms, verbatim e.g. 'FOB Shenzhen'. Null if absent."},
        "manufacturer": {"type": ["string", "null"], "description": "Brand the supplier is quoting, verbatim. Null if unstated."},
        "mfg_part_number": {
            "type": ["string", "null"],
            "description": (
                "The manufacturer part number the supplier is quoting, verbatim. Record their OWN "
                "number even when it differs from the buyer's — that difference is a substitution. "
                "When the supplier restates the SAME number the buyer specified, record it here too; "
                "confirming the requested part is not the same as stating none. Null only when the "
                "supplier names no manufacturer part number anywhere in the thread."
            ),
        },
        "price_breaks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "part_number": {
                        "type": "string",
                        "description": "The BUYER's internal part number this row prices, verbatim — not the manufacturer's.",
                    },
                    "quantity": {"type": "integer"},
                    "unit_price": {"type": "string", "description": "Verbatim as written, e.g. 'USD 45.00/pc'."},
                    "lead_time": {
                        "type": ["string", "null"],
                        "description": "Lead time for THIS row, verbatim. Null only if none is stated for it.",
                    },
                    "service_tier": {
                        "type": ["string", "null"],
                        "description": "Scenario label for this row, verbatim. Null when the quote has no tier split.",
                    },
                },
                "required": ["part_number", "quantity", "unit_price", "lead_time", "service_tier"],
            },
            "description": "One row per (service_tier, quantity). Never merge or drop a tier.",
        },
        "long_lead_time_parts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parts with lead time >= 8 calendar weeks. Business days are not calendar weeks.",
        },
        "coo": {"type": ["string", "null"], "description": "Country of origin, verbatim. Null if absent."},
        "payment_terms": {"type": ["string", "null"], "description": "Payment terms, verbatim. Null if absent or TBD."},
        "moq": {"type": ["string", "null"], "description": "Minimum order quantity if stated. Null if absent."},
        "nre": {"type": ["string", "null"], "description": "NRE / one-time tooling cost if confirmed. Null if absent or TBD."},
        "blocking_question": {
            "type": ["string", "null"],
            "description": (
                "A question the supplier needs the BUYER to answer before a commercial field can be "
                "settled. Null if none."
            ),
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
                                "items": {"type": "string", "enum": ["unit_price", "lead_time"]},
                            },
                            "service_tier": {"type": ["string", "null"]},
                        },
                        "required": ["part_number", "missing"],
                    },
                },
                "quote_level": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["payment_terms", "coo", "moq", "nre"],
                    },
                    "description": "Quote-wide fields the supplier has not provided.",
                },
            },
            "required": ["per_part", "quote_level"],
        },
    },
    "required": [
        "rfq_reference", "supplier_name", "quote_id", "quote_valid_until", "incoterms",
        "manufacturer", "mfg_part_number", "price_breaks", "long_lead_time_parts",
        "coo", "payment_terms", "moq", "nre", "blocking_question", "missing_fields",
    ],
}

_EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": "Record everything present in this RFQ email thread.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["rfq_sent", "supplier_quote", "supplier_reminder", "ignore"],
                "description": "What the LATEST email in the thread is doing.",
            },
            "rfq_requirements": _RFQ_REQUIREMENTS_SCHEMA,
            "supplier_quote": _SUPPLIER_QUOTE_SCHEMA,
        },
        "required": ["classification", "rfq_requirements", "supplier_quote"],
    },
}

# ── Response tools — the action IS the tool the agent chooses ──────────────────

_FIELD_ENUM = ["price_breaks", "lead_time", "coo", "payment_terms", "moq", "nre",
               "mfg_part_number"]

_RESPONSE_TOOLS = [
    {
        "name": "send_supplier_followup",
        "description": (
            "Ask the supplier for the fields that are still outstanding. Use only when the "
            "buyer's required fields are not all answered AND nothing needs the buyer first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields_requested": {
                    "type": "array",
                    "items": {"type": "string", "enum": _FIELD_ENUM},
                    "description": (
                        "Exactly the fields this email asks for. Must match the email body — "
                        "every field listed here is asked for in the body, and nothing else is."
                    ),
                },
                "subject": {"type": "string", "description": "Subject line, normally 'Re: <original subject>'."},
                "body": {"type": "string", "description": "The email body as it will be sent."},
            },
            "required": ["fields_requested", "subject", "body"],
        },
    },
    {
        "name": "flag_buyer",
        "description": (
            "Escalate to the buyer. Use when the supplier is blocked waiting on the buyer, or "
            "quoted a different manufacturer part number than the RFQ specified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["blocking_question", "part_substitution"],
                    "description": "Why this needs the buyer.",
                },
                "body": {"type": "string", "description": "The note to the buyer stating what must be decided."},
            },
            "required": ["reason", "body"],
        },
    },
    {
        "name": "mark_ready_for_review",
        "description": (
            "No reply needed. Use when every required field is answered and nothing is blocked, "
            "or when the thread has no supplier to respond to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "One line on why nothing is outstanding."},
            },
            "required": ["note"],
        },
    },
]


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


# ── Agent 1: extraction — one call, whole thread ──────────────────────────────

def _build_rfq_requirements(data: dict | None) -> RFQRequirements | None:
    if not data:
        return None
    return RFQRequirements(
        quantities_requested=data.get("quantities_requested") or [],
        required_fields=data.get("required_fields") or [],
        requested_tiers=data.get("requested_tiers") or [],
        our_part_number=data.get("our_part_number"),
        manufacturer=data.get("manufacturer"),
        mfg_part_number=data.get("mfg_part_number"),
    )


def _build_supplier_quote(data: dict | None) -> SupplierQuoteData | None:
    if not data:
        return None
    missing = data.get("missing_fields") or {}
    return SupplierQuoteData(
        rfq_reference=data.get("rfq_reference"),
        supplier_name=data.get("supplier_name"),
        quote_id=data.get("quote_id"),
        quote_valid_until=data.get("quote_valid_until"),
        incoterms=data.get("incoterms"),
        price_breaks=[
            PriceBreak(pb["part_number"], pb["quantity"], pb["unit_price"],
                       pb.get("lead_time"), pb.get("service_tier"))
            for pb in data.get("price_breaks") or []
        ],
        long_lead_time_parts=data.get("long_lead_time_parts") or [],
        coo=data.get("coo"),
        payment_terms=data.get("payment_terms"),
        moq=data.get("moq"),
        nre=data.get("nre"),
        blocking_question=data.get("blocking_question"),
        missing_fields=MissingFields(
            per_part=[
                PartMissing(pm["part_number"], pm.get("missing") or [], pm.get("service_tier"))
                for pm in missing.get("per_part") or []
            ],
            quote_level=missing.get("quote_level") or [],
        ),
        manufacturer=data.get("manufacturer"),
        mfg_part_number=data.get("mfg_part_number"),
    )


def process_thread(messages: list[EmailMessage]) -> ProcessingResult:
    """Read the thread once and record everything in it."""
    if not messages:
        raise ValueError("Cannot process an empty email thread")

    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        system=_system("extraction.txt"),
        tools=[_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_extraction"},
        messages=[{"role": "user", "content": _format_thread(messages)}],
    )
    data = next(block.input for block in response.content if block.type == "tool_use")
    return ProcessingResult(
        classification=data["classification"],
        rfq_requirements=_build_rfq_requirements(data.get("rfq_requirements")),
        supplier_quote=_build_supplier_quote(data.get("supplier_quote")),
    )


# ── Agent 2: response — the action is the tool it picks ───────────────────────

def decide_response(messages: list[EmailMessage], result: ProcessingResult) -> ResponseAction:
    """Let the agent choose one of three actions and write the copy for it."""
    briefing = "\n\n".join([
        _format_thread(messages),
        "<extraction>",
        json.dumps(asdict(result), indent=2, ensure_ascii=False),
        "</extraction>",
        "Choose exactly one action for the latest email in this thread.",
    ])
    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        system=_system("response.txt"),
        tools=_RESPONSE_TOOLS,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": briefing}],
    )
    block = next(b for b in response.content if b.type == "tool_use")
    data = block.input
    if block.name == "send_supplier_followup":
        return ResponseAction(
            action="chase_supplier",
            fields_requested=data.get("fields_requested") or [],
            subject=data.get("subject"),
            body=data.get("body"),
        )
    if block.name == "flag_buyer":
        return ResponseAction(
            action="flag_buyer",
            reason=data.get("reason"),
            body=data.get("body"),
        )
    return ResponseAction(action="ready_for_review", note=data.get("note"))
