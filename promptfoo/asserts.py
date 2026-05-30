"""Promptfoo Python assertions for ForgeFlow extraction.

Each receives the provider output (JSON string of the ExtractedCase) and the
test context (with expected labels in vars), and returns a GradingResult.
"""

from __future__ import annotations

import json
import re

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _result(ok: bool, reason: str) -> dict:
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reason": reason}


def check_classification(output, context):
    ex = json.loads(output)
    expected = context["vars"]["expected_classification"]
    got = ex["classification"]
    return _result(got == expected, f"classification: got {got!r}, expected {expected!r}")


def check_field_presence(output, context):
    ex = json.loads(output)
    v = context["vars"]
    checks = {
        "price_breaks": (bool(ex["price_breaks"]), v["expected_price_breaks"]),
        "production_lead_time": (bool(ex["production_lead_time"]), v["expected_production_lead_time"]),
        "long_lead_time_parts": (bool(ex["long_lead_time_parts"]), v["expected_long_lead_time_parts"]),
        "payment_terms": (bool(ex["payment_terms"]), v["expected_payment_terms"]),
    }
    wrong = [name for name, (got, exp) in checks.items() if got != exp]
    return _result(not wrong, "field presence ok" if not wrong else f"mismatched: {wrong}")


def check_missing_fields(output, context):
    ex = json.loads(output)
    got = sorted(ex["missing_fields"])
    expected = sorted(context["vars"]["expected_missing_fields"])
    return _result(got == expected, f"missing_fields: got {got}, expected {expected}")


def check_grounding(output, context):
    ex = json.loads(output)
    text = context["vars"]["email_text"].replace(",", "")
    emitted: list[str] = []
    for pb in ex["price_breaks"]:
        emitted += _NUMBER_RE.findall(pb)
    if ex["production_lead_time"]:
        emitted += _NUMBER_RE.findall(ex["production_lead_time"])
    fabricated = [n for n in emitted if n not in text]
    return _result(not fabricated, "all values grounded" if not fabricated else f"fabricated: {fabricated}")
