"""Quick debug dashboard for the LLM extractor.

Runs the Claude agent over each eval case and prints, per email:
the INPUT (subject + body snippet), what the MODEL produced, and the
EXPECTED labels — so you can eyeball exactly what's happening and why a
metric passed or failed.

    set -a; source .env; set +a
    PYTHONPATH=src python3 eval_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from forgeflow.agent import extract_case  # noqa: E402  (LLM only)
from forgeflow.parser import parse_email_file  # noqa: E402


def _mark(ok: bool) -> str:
    return "OK  " if ok else "FAIL"


def main() -> None:
    cases = json.loads((ROOT / "data" / "eval_cases" / "eval_cases.json").read_text())
    for case in cases:
        message = parse_email_file(ROOT / case["email_file"])
        ex = extract_case([message])
        body = " ".join(message.body_text.split())[:180]

        print("=" * 90)
        print(case["email_file"])
        print("-" * 90)
        print(f"INPUT subject : {message.subject}")
        print(f"INPUT body    : {body}…")
        print("MODEL OUTPUT  :")
        print(f"    classification      : {ex.classification}")
        print(f"    price_breaks        : {ex.price_breaks}")
        print(f"    production_lead_time: {ex.production_lead_time}")
        print(f"    long_lead_time_parts: {ex.long_lead_time_parts}")
        print(f"    payment_terms       : {ex.payment_terms}")
        print(f"    missing_fields      : {ex.missing_fields}")
        print("CHECK vs EXPECTED :")
        print(
            f"    [{_mark(ex.classification == case['expected_classification'])}] "
            f"classification: got {ex.classification!r}, expected {case['expected_classification']!r}"
        )
        for field, got in (
            ("price_breaks", bool(ex.price_breaks)),
            ("production_lead_time", bool(ex.production_lead_time)),
            ("long_lead_time_parts", bool(ex.long_lead_time_parts)),
            ("payment_terms", bool(ex.payment_terms)),
        ):
            exp = case[f"expected_{field}"]
            print(f"    [{_mark(got == exp)}] {field} present: got {got}, expected {exp}")
        exp_missing = sorted(case["expected_missing_fields"])
        got_missing = sorted(ex.missing_fields)
        print(
            f"    [{_mark(got_missing == exp_missing)}] missing_fields: "
            f"got {got_missing}, expected {exp_missing}"
        )
    print("=" * 90)


if __name__ == "__main__":
    main()
