"""Promptfoo integration for the RFQ classification router."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from forgeflow.agent import classify_thread  # noqa: E402
from forgeflow.parser import parse_email_file  # noqa: E402


def call_api(prompt, options, context):
    thread_files = context["vars"].get("thread_emails")
    if isinstance(thread_files, str):
        thread_files = json.loads(thread_files)
    if not thread_files:
        thread_files = [context["vars"]["email_file"]]

    messages = [parse_email_file(ROOT / f) for f in thread_files]
    return {"output": json.dumps(asdict(classify_thread(messages)), indent=2)}


def load_tests():
    cases = json.loads((ROOT / "data" / "eval_cases" / "eval_cases.json").read_text())
    tests = []
    for case in cases:
        thread_files = case.get("thread_emails", [case["email_file"]])
        thread_messages = [parse_email_file(ROOT / f) for f in thread_files]
        latest = thread_messages[-1]
        email_text = "\n\n---\n\n".join(
            f"Subject: {m.subject}\nFrom: {m.sender}\nTo: {m.recipients}\n\n{m.body_text}"
            for m in thread_messages
        )
        tests.append(
            {
                "description": f"{case['email_file']} -> {case['expected_classification']}",
                "vars": {
                    "email_file": case["email_file"],
                    "thread_emails": json.dumps(thread_files),
                    "email_text": email_text,
                    "latest_subject": latest.subject,
                    "latest_sender": latest.sender,
                    "expected_classification": case["expected_classification"],
                    "expected_price_breaks": case["expected_price_breaks"],
                    "expected_production_lead_time": case["expected_production_lead_time"],
                    "expected_long_lead_time_parts": case["expected_long_lead_time_parts"],
                    "expected_payment_terms": case["expected_payment_terms"],
                    "expected_missing_fields": json.dumps(case["expected_missing_fields"]),
                },
            }
        )
    return tests


def check_classification(output, context):
    result = json.loads(output)
    expected = context["vars"]["expected_classification"]
    got = result["classification"]
    ok = got == expected
    return {
        "pass": ok,
        "score": 1.0 if ok else 0.0,
        "reason": f"classification: got {got!r}, expected {expected!r}",
    }


def check_quote_signals(output, context):
    result = json.loads(output)
    vars_ = context["vars"]
    checks = {
        "has_price_breaks": (result["has_price_breaks"], vars_["expected_price_breaks"]),
        "has_production_lead_time": (
            result["has_production_lead_time"],
            vars_["expected_production_lead_time"],
        ),
        "has_long_lead_time_parts": (
            result["has_long_lead_time_parts"],
            vars_["expected_long_lead_time_parts"],
        ),
        "has_payment_terms": (result["has_payment_terms"], vars_["expected_payment_terms"]),
    }
    wrong = [name for name, (got, expected) in checks.items() if got != expected]
    ok = not wrong
    return {
        "pass": ok,
        "score": 1.0 if ok else 0.0,
        "reason": "quote signals ok" if ok else f"mismatched quote signals: {wrong}",
    }


def check_missing_fields(output, context):
    result = json.loads(output)
    got = sorted(result["missing_fields"])
    expected = sorted(json.loads(context["vars"]["expected_missing_fields"]))
    ok = got == expected
    return {
        "pass": ok,
        "score": 1.0 if ok else 0.0,
        "reason": f"missing_fields: got {got}, expected {expected}",
    }
