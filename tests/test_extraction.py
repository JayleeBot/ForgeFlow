"""DeepEval evaluation workflow for ForgeFlow extraction.

Run locally (fully offline — deterministic metrics, no model calls):
    deepeval test run tests/test_extraction.py

The metrics read the result of the rule-based `extract_case`; this is the
baseline the future agent (agent.py) must match or beat. To grade the agent
later, only `_load_test_cases` changes — the metrics stay identical.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from deepeval import assert_test  # noqa: E402
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from forgeflow.parser import parse_email_file  # noqa: E402

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _extract(messages):
    # LLM only: the eval grades the Claude agent (hits the API). No regex path.
    from forgeflow.agent import extract_case
    return extract_case(messages)


def _load_test_cases() -> list[LLMTestCase]:
    cases = json.loads((ROOT / "data" / "eval_cases" / "eval_cases.json").read_text())
    test_cases = []
    for case in cases:
        message = parse_email_file(ROOT / case["email_file"])
        extracted = _extract([message])
        email_text = f"{message.subject}\n{message.body_text}"
        test_cases.append(
            LLMTestCase(
                name=case["email_file"],
                input=email_text,
                actual_output=extracted.summary,
                additional_metadata={
                    "extracted": asdict(extracted),
                    "expected": case,
                    "email_text": email_text,
                },
            )
        )
    return test_cases


class _DeterministicMetric(BaseMetric):
    """Base for code-graded (no-LLM) metrics: subclasses implement `_evaluate`."""

    def __init__(self, threshold: float = 1.0):
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase) -> float:
        self.score, self.reason = self._evaluate(test_case.additional_metadata)
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success

    def _evaluate(self, meta: dict) -> tuple[float, str]:
        raise NotImplementedError


class ClassificationMetric(_DeterministicMetric):
    @property
    def __name__(self):
        return "Classification Match"

    def _evaluate(self, meta):
        got = meta["extracted"]["classification"]
        exp = meta["expected"]["expected_classification"]
        return (1.0 if got == exp else 0.0, f"got '{got}', expected '{exp}'")


class FieldPresenceMetric(_DeterministicMetric):
    @property
    def __name__(self):
        return "Field Presence"

    def _evaluate(self, meta):
        ex, md = meta["extracted"], meta["expected"]
        checks = {
            "price_breaks": (bool(ex["price_breaks"]), md["expected_price_breaks"]),
            "production_lead_time": (bool(ex["production_lead_time"]), md["expected_production_lead_time"]),
            "long_lead_time_parts": (bool(ex["long_lead_time_parts"]), md["expected_long_lead_time_parts"]),
            "payment_terms": (bool(ex["payment_terms"]), md["expected_payment_terms"]),
        }
        wrong = [name for name, (got, exp) in checks.items() if got != exp]
        return (1.0 if not wrong else 0.0, "all present-flags match" if not wrong else f"mismatched: {wrong}")


class MissingFieldsMetric(_DeterministicMetric):
    @property
    def __name__(self):
        return "Missing Fields"

    def _evaluate(self, meta):
        got = set(meta["extracted"]["missing_fields"])
        exp = set(meta["expected"]["expected_missing_fields"])
        return (1.0 if got == exp else 0.0, f"got {sorted(got)}, expected {sorted(exp)}")


class GroundingMetric(_DeterministicMetric):
    """Anti-fabrication: every price/lead-time number emitted must appear
    verbatim in the source email — the cardinal LLM failure to catch."""

    @property
    def __name__(self):
        return "Grounding (no fabrication)"

    def _evaluate(self, meta):
        ex = meta["extracted"]
        text = meta["email_text"].replace(",", "")
        emitted: list[str] = []
        for pb in ex["price_breaks"]:
            emitted += _NUMBER_RE.findall(pb)
        if ex["production_lead_time"]:
            emitted += _NUMBER_RE.findall(ex["production_lead_time"])
        fabricated = [n for n in emitted if n not in text]
        return (1.0 if not fabricated else 0.0, "all values grounded" if not fabricated else f"fabricated: {fabricated}")


@pytest.mark.parametrize("test_case", _load_test_cases())
def test_extraction(test_case: LLMTestCase):
    assert_test(
        test_case,
        [ClassificationMetric(), FieldPresenceMetric(), MissingFieldsMetric(), GroundingMetric()],
    )
