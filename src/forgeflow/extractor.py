from __future__ import annotations

import re
from dataclasses import dataclass

from forgeflow.models import EmailMessage


PROD_LT_RE = re.compile(
    r"(?:production\s+lead\s+time|lead\s+time|plt|build\s+time|delivery\s+time)"
    r"\s*[:\-]?\s*\**\s*([\d]+\s*(?:business\s+)?(?:weeks?|wks?|days?))",
    re.IGNORECASE,
)
_QTY_LINE_RE = re.compile(r"(?:qty|quantity)\s*[:\-]\s*([\d,]+)", re.IGNORECASE)
_UNIT_PRICE_LINE_RE = re.compile(
    r"(?:unit\s*price|price\s*per\s*(?:unit|pcs?|piece)|each)\s*[:\-]\s*"
    r"(?:USD|EUR|GBP|\$)?\s*([\d,]+\.?\d+)",
    re.IGNORECASE,
)
_INLINE_PB_RE = re.compile(
    r"([\d,]+)\s*(?:pcs?|units?|x\b)?\s*@\s*(?:USD|EUR|GBP|\$)\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_LT_WEEKS_RE = re.compile(
    r"lead\s+time\s*[:\-]?\s*\**\s*(\d+)\s*\**\s*(weeks?|wks?)",
    re.IGNORECASE,
)
_PN_LINE_RE = re.compile(r"^\s*PN\s*[:\-]\s*(\S+)", re.IGNORECASE | re.MULTILINE)
MOQ_RE = re.compile(
    r"(?:moq|minimum\s*order\s*(?:quantity)?)[^\n]{0,20}?(\d+)",
    re.IGNORECASE,
)
PAYMENT_RE = re.compile(
    r"\b(net\s*\d+|net\s*\d+\s*days?|cod\b|prepay|50%\s*upfront|[0-9]+%\s*(?:upfront|deposit)[^,\n]{0,30})",
    re.IGNORECASE,
)
NRE_RE = re.compile(
    r"(?:nre|non[- ]recurring\s*engineering)[^\n]{0,30}?\$?([\d,]+\.?\d*)",
    re.IGNORECASE,
)
COO_RE = re.compile(
    r"(?:coo|country\s*of\s*origin|made\s*in|built?\s*in|manufactured\s*in)[^\n]{0,30}?(usa|united\s*states|mexico|china|taiwan|vietnam|malaysia|india|germany|japan)",
    re.IGNORECASE,
)
QUOTE_RESPONSE_HINTS = (
    "please find our quote",
    "our quotation",
    "quote for",
    "pricing for",
    "we are pleased to quote",
    "attached is our quote",
    "price quote",
    "unit price",
    "lead time",
    "production lead time",
    "nre",
    "non-recurring",
    "payment terms",
)
SUPPLIER_FOLLOWUP_HINTS = (
    "following up",
    "checking in",
    "any update on",
    "wanted to follow up",
    "did you receive our quote",
)
# Supplier emails that reference a prior quote as still-valid and provide a
# missing piece (NRE, payment terms, etc.). The quote thread is complete.
_QUOTE_COMPLETION_HINTS = (
    "previously quoted",
    "remain as quoted",
)
# Buyer/agent emails request information rather than provide it.
# These patterns take priority over SUPPLIER_FOLLOWUP_HINTS.
BUYER_REQUEST_HINTS = (
    "[forgeflow",
    "we are issuing an rfq",
    "automated follow-up on outstanding",
    "we are still missing the following",
    "flag for buyer",
)
# Detects a supplier question directed at the buyer that must be answered before
# the quote can be completed (e.g. "Could you confirm what grade of mold you need?").
# Excludes polite closings ("let us know if you have any questions") by requiring a
# specific action verb directly after the trigger phrase.
_SUPPLIER_QUESTION_RE = re.compile(
    r"(?:could you (?:confirm|clarify|provide|specify|advise)|"
    r"can you (?:confirm|clarify|provide|specify)|"
    r"please (?:confirm|clarify|advise|specify)|"
    r"what (?:type|grade|level|version|specification|specs?) (?:of|do you)|"
    r"which (?:option|version|grade|type|level))"
    r"[^?]{0,300}\?",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ExtractedCase:
    classification: str
    supplier_name: str | None
    supplier_email: str | None
    price_breaks: list[str]
    production_lead_time: str | None
    long_lead_time_parts: list[str]
    moq: str | None
    payment_terms: str | None
    nre: str | None
    coo: str | None
    missing_fields: list[str]
    summary: str
    supplier_pending_question: str | None


def extract_case(messages: list[EmailMessage]) -> ExtractedCase:
    latest = messages[-1]
    combined_text = "\n".join(m.body_text for m in messages if m.body_text)
    latest_lower = f"{latest.subject}\n{latest.body_text or ''}".lower()
    combined_lower = f"{latest.subject}\n{combined_text}".lower()
    classification = _classify(latest_lower)
    supplier_name, supplier_email = _parse_sender(latest.sender)
    if classification == "ignore":
        summary = f"[{supplier_name or 'Unknown'}] Ignored — not a supplier quote or followup."
        return ExtractedCase(
            classification="ignore", supplier_name=supplier_name,
            supplier_email=supplier_email, price_breaks=[],
            production_lead_time=None, long_lead_time_parts=[], moq=None,
            payment_terms=None, nre=None, coo=None, missing_fields=[],
            summary=summary, supplier_pending_question=None,
        )
    price_breaks = _extract_price_breaks(combined_text)
    production_lead_time = _find_first(PROD_LT_RE, combined_text)
    long_lead_time_parts = _extract_long_lead_parts(combined_text)
    moq = _find_first(MOQ_RE, combined_text)
    payment_terms = _find_first(PAYMENT_RE, combined_text)
    nre = _find_nre(combined_text)
    coo = _find_first(COO_RE, combined_text)
    supplier_pending_question = _detect_supplier_question(combined_text) if classification != "ignore" else None
    missing_fields = _derive_missing_fields(classification, price_breaks, production_lead_time, payment_terms)
    if any(hint in combined_lower for hint in _QUOTE_COMPLETION_HINTS) and missing_fields:
        missing_fields = []
    if supplier_pending_question and missing_fields:
        missing_fields = ["buyer_input_required"]
    summary = _build_summary(classification, supplier_name, price_breaks, production_lead_time, long_lead_time_parts, moq, payment_terms, nre, coo, missing_fields, supplier_pending_question)
    return ExtractedCase(
        classification=classification,
        supplier_name=supplier_name,
        supplier_email=supplier_email,
        price_breaks=price_breaks,
        production_lead_time=production_lead_time,
        long_lead_time_parts=long_lead_time_parts,
        moq=moq,
        payment_terms=payment_terms,
        nre=nre,
        coo=coo,
        missing_fields=missing_fields,
        summary=summary,
        supplier_pending_question=supplier_pending_question,
    )


def _classify(text: str) -> str:
    # Classification must reflect the direction of information flow, not just
    # keyword presence. The correct question is: is this email PROVIDING quote
    # data (supplier -> buyer) or REQUESTING it (buyer -> supplier)?
    #
    # Pure keyword matching fails here because words like "follow-up" appear in
    # both supplier check-ins and agent-generated chasers. Without checking
    # direction, a buyer email asking "please confirm your payment terms" would
    # match SUPPLIER_FOLLOWUP_HINTS and be misclassified as supplier_reminder.
    #
    # Fix: check for buyer/agent signals first. These patterns indicate the email
    # is outbound from the buyer side -- requesting data, not supplying it -- so
    # they take priority over any supplier-side hints that might also match.
    if any(hint in text for hint in BUYER_REQUEST_HINTS):
        return "ignore"
    if any(hint in text for hint in _QUOTE_COMPLETION_HINTS):
        return "quote_received"
    if any(hint in text for hint in SUPPLIER_FOLLOWUP_HINTS):
        return "supplier_reminder"
    if any(hint in text for hint in QUOTE_RESPONSE_HINTS):
        return "quote_received"
    return "ignore"


def _parse_sender(sender: str) -> tuple[str | None, str | None]:
    match = re.match(r'(?:"?([^"<]+)"?\s*)?<([^>]+)>', sender)
    if match:
        name = match.group(1).strip() if match.group(1) else None
        email = match.group(2).strip()
        return name, email
    return None, sender.strip() if "@" in sender else None


def _extract_price_breaks(text: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    # Inline format: "500 pcs @ USD 7.80"
    for m in _INLINE_PB_RE.finditer(text):
        _add_pb(results, seen, m.group(1).replace(",", ""), m.group(2))

    # Multi-line format: Qty on one line, Unit Price within the next few lines
    lines = text.splitlines()
    last_qty: str | None = None
    last_qty_idx: int = -1
    for i, line in enumerate(lines):
        qty_m = _QTY_LINE_RE.search(line)
        price_m = _UNIT_PRICE_LINE_RE.search(line)
        if qty_m:
            last_qty = qty_m.group(1).replace(",", "")
            last_qty_idx = i
        if price_m and last_qty is not None and (i - last_qty_idx) <= 6:
            _add_pb(results, seen, last_qty, price_m.group(1))
            last_qty = None

    # Fallback: standalone unit price line without a nearby qty
    if not results:
        m = _UNIT_PRICE_LINE_RE.search(text)
        if m:
            results.append(f"unit@${m.group(1)}")

    return results


def _add_pb(results: list[str], seen: set[str], qty: str, price: str) -> None:
    if not price or price == "0":
        return
    entry = f"{qty}@${price}"
    key = entry.lower()
    if key not in seen:
        results.append(entry)
        seen.add(key)


def _extract_long_lead_parts(text: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    lines = text.splitlines()
    last_pn: str | None = None
    for line in lines:
        pn_m = _PN_LINE_RE.search(line)
        if pn_m:
            last_pn = pn_m.group(1).strip()
        lt_m = _LT_WEEKS_RE.search(line)
        if lt_m and last_pn:
            try:
                weeks = int(lt_m.group(1))
                if weeks >= 8:
                    entry = f"{last_pn}: {weeks}wks"
                    key = entry.lower()
                    if key not in seen:
                        results.append(entry)
                        seen.add(key)
            except ValueError:
                continue
    return results


def _find_nre(text: str) -> str | None:
    match = NRE_RE.search(text)
    if match:
        return f"${match.group(1)}"
    return None


def _find_first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _detect_supplier_question(text: str) -> str | None:
    match = _SUPPLIER_QUESTION_RE.search(text)
    return match.group(0).strip() if match else None


def _derive_missing_fields(
    classification: str,
    price_breaks: list[str],
    production_lead_time: str | None,
    payment_terms: str | None,
) -> list[str]:
    if classification == "ignore":
        return []
    missing: list[str] = []
    if not price_breaks:
        missing.append("unit_price")
    if not production_lead_time:
        missing.append("production_lead_time")
    if not payment_terms:
        missing.append("payment_terms")
    return missing


def _build_summary(
    classification: str,
    supplier_name: str | None,
    price_breaks: list[str],
    production_lead_time: str | None,
    long_lead_time_parts: list[str],
    moq: str | None,
    payment_terms: str | None,
    nre: str | None,
    coo: str | None,
    missing_fields: list[str],
    supplier_pending_question: str | None,
) -> str:
    supplier = supplier_name or "Unknown supplier"
    prices = ", ".join(price_breaks) if price_breaks else "no pricing found"
    plt = production_lead_time or "no PLT found"
    llt = ", ".join(long_lead_time_parts) if long_lead_time_parts else "none"
    terms = payment_terms or "not stated"
    nre_str = nre or "none"
    coo_str = coo or "not stated"
    missing = ", ".join(missing_fields) if missing_fields else "none"
    summary = (
        f"{classification} from {supplier}; "
        f"prices: {prices}; PLT: {plt}; long-LT parts: {llt}; "
        f"MOQ: {moq or 'not stated'}; terms: {terms}; "
        f"NRE: {nre_str}; COO: {coo_str}; missing: {missing}"
    )
    if supplier_pending_question:
        summary += (
            f" | FLAG FOR BUYER: Supplier is waiting for your input before completing "
            f"the quote. Question: {supplier_pending_question}"
        )
    return summary
