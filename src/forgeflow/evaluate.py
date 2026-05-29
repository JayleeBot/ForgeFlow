from __future__ import annotations

import json
from pathlib import Path

from forgeflow.extractor import ExtractedCase, extract_case
from forgeflow.parser import parse_email_file


def run_eval(root: Path) -> bool:
    cases_path = root / "data" / "eval_cases" / "eval_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    passed = 0
    for case in cases:
        message = parse_email_file(root / case["email_file"])
        extracted = extract_case([message])
        failures = _failed_checks(case, extracted)
        if not failures:
            passed += 1
            print(f"[PASS] {case['email_file']}")
        else:
            print(f"[FAIL] {case['email_file']}")
            for name, expected, actual in failures:
                print(f"    {name}: expected {expected!r}, got {actual!r}")

    total = len(cases)
    print(f"\n{passed}/{total} cases passed")
    return passed == total


def _failed_checks(case: dict, extracted: ExtractedCase) -> list[tuple[str, object, object]]:
    checks = [
        ("classification", case["expected_classification"], extracted.classification),
        ("price_breaks", case["expected_price_breaks"], bool(extracted.price_breaks)),
        (
            "production_lead_time",
            case["expected_production_lead_time"],
            bool(extracted.production_lead_time),
        ),
        (
            "long_lead_time_parts",
            case["expected_long_lead_time_parts"],
            bool(extracted.long_lead_time_parts),
        ),
        ("payment_terms", case["expected_payment_terms"], bool(extracted.payment_terms)),
        (
            "missing_fields",
            set(case["expected_missing_fields"]),
            set(extracted.missing_fields),
        ),
    ]
    return [(name, expected, actual) for name, expected, actual in checks if expected != actual]
