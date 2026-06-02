"""Promptfoo test generator: one test per eval case, carrying the email text
and the expected labels as vars so the provider and assertions can use them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from forgeflow.parser import parse_email_file  # noqa: E402


def load_tests():
    cases = json.loads((ROOT / "data" / "eval_cases" / "eval_cases.json").read_text())
    tests = []
    for case in cases:
        message = parse_email_file(ROOT / case["email_file"])
        tests.append(
            {
                "description": case["email_file"],
                "vars": {
                    "email_file": case["email_file"],
                    "email_text": f"{message.subject}\n{message.body_text}",
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
