"""Eval harness for the RFQ processing agent.

Runs `process_thread` over `data/eval_cases/eval_cases.json` and scores each
result with a set of graders. A grader is a plain function taking the agent's
result dict plus the case's expectations and returning a pass/fail with a
human-readable reason.

    PYTHONPATH=src python3 -m forgeflow.cli eval
    PYTHONPATH=src python3 -m forgeflow.cli eval --save runs/base.json
    PYTHONPATH=src python3 -m forgeflow.cli eval --compare runs/base.json

Cases opt in to the optional graders by including the relevant `expected_*`
key; omit the key to skip that check for that case.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from forgeflow.agent import process_thread
from forgeflow.parser import parse_email_file

DEFAULT_CASE_FILE = Path("data/eval_cases/eval_cases.json")
DEFAULT_WORKERS = 6


@dataclass(slots=True)
class Grade:
    grader: str
    passed: bool
    reason: str


@dataclass(slots=True)
class CaseResult:
    email_file: str
    grades: list[Grade] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(g.passed for g in self.grades)


# ── Graders ────────────────────────────────────────────────────────────────────

def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    return bool(str(value).strip())


def _norm(value) -> str:
    return (value or "").strip().lower()


def grade_classification(result: dict, case: dict) -> Grade:
    got, expected = result["classification"], case["expected_classification"]
    return Grade("classification", got == expected,
                 f"got {got!r}, expected {expected!r}")


def grade_quote_signals(result: dict, case: dict) -> Grade:
    quote = result.get("supplier_quote") or {}
    price_breaks = quote.get("price_breaks") or []
    # lead_time is per-part: present only if every quoted row carries one.
    lead_time = bool(price_breaks) and all(_present(pb.get("lead_time")) for pb in price_breaks)

    checks = {
        "price_breaks": (_present(quote.get("price_breaks")), case["expected_price_breaks"]),
        "lead_time": (lead_time, case["expected_production_lead_time"]),
        "long_lead_time_parts": (_present(quote.get("long_lead_time_parts")),
                                 case["expected_long_lead_time_parts"]),
        "payment_terms": (_present(quote.get("payment_terms")), case["expected_payment_terms"]),
    }
    wrong = [f"{name} (got {got}, expected {exp})"
             for name, (got, exp) in checks.items() if got != exp]
    return Grade("quote_signals", not wrong, "ok" if not wrong else "; ".join(wrong))


def grade_part_numbers(result: dict, case: dict) -> Grade:
    price_breaks = (result.get("supplier_quote") or {}).get("price_breaks") or []
    missing = [pb for pb in price_breaks if not str(pb.get("part_number") or "").strip()]
    return Grade("part_numbers", not missing,
                 "all price breaks carry a part_number" if not missing
                 else f"{len(missing)} price break(s) missing part_number")


def grade_missing_fields(result: dict, case: dict) -> Grade:
    def norm(mf) -> tuple:
        mf = mf or {}
        per_part = sorted(
            (p.get("part_number", ""), p.get("service_tier"), sorted(p.get("missing", [])))
            for p in mf.get("per_part", [])
        )
        return per_part, sorted(mf.get("quote_level", []))

    got = norm((result.get("supplier_quote") or {}).get("missing_fields"))
    expected = norm(case["expected_missing_fields"])
    return Grade("missing_fields", got == expected, f"got {got}, expected {expected}")


def grade_service_tiers(result: dict, case: dict) -> Grade:
    """RFQ-side requested tiers, and quote-side price-break tiers.

    `expected_price_break_tiers: null` asserts the quote has NO tiers (a
    hallucination guard); a list asserts the distinct tiers match, each covering
    the same quantities at prices that actually differ between tiers — which
    catches tiers that were silently merged or dropped.
    """
    reasons: list[str] = []

    expected_rt = case.get("expected_requested_tiers")
    if expected_rt is not None:
        got_rt = sorted((result.get("rfq_requirements") or {}).get("requested_tiers") or [])
        if got_rt != sorted(expected_rt):
            reasons.append(f"requested_tiers: got {got_rt}, expected {sorted(expected_rt)}")

    if "expected_price_break_tiers" in case:
        expected_pbt = case["expected_price_break_tiers"]
        price_breaks = (result.get("supplier_quote") or {}).get("price_breaks") or []
        seen = [pb.get("service_tier") for pb in price_breaks]
        distinct = sorted({t for t in seen if t})
        if expected_pbt is None:
            if any(seen):
                reasons.append(f"expected no service tiers, got {distinct}")
        elif distinct != sorted(expected_pbt):
            reasons.append(f"price-break tiers: got {distinct}, expected {sorted(expected_pbt)}")
        else:
            by_tier: dict[str, dict] = {}
            for pb in price_breaks:
                by_tier.setdefault(pb.get("service_tier"), {})[pb.get("quantity")] = pb.get("unit_price")
            qty_sets = {t: sorted(m.keys()) for t, m in by_tier.items()}
            ref = qty_sets[sorted(qty_sets)[0]]
            if any(qtys != ref for qtys in qty_sets.values()):
                reasons.append(f"tiers cover different quantities: {qty_sets}")
            tiers = sorted(by_tier)
            a, b = by_tier[tiers[0]], by_tier[tiers[1]]
            shared = set(a) & set(b)
            if shared and all(a[q] == b[q] for q in shared):
                reasons.append("tiers have identical prices at every shared quantity (merged?)")

    return Grade("service_tiers", not reasons, "ok" if not reasons else "; ".join(reasons))


def grade_mfg(result: dict, case: dict) -> Grade:
    """MFG part-number capture on the RFQ side, and substitution detection on the quote side."""
    reasons: list[str] = []
    expected_mfg = case.get("expected_mfg_part_number", "__skip__")

    if expected_mfg != "__skip__":
        got = (result.get("rfq_requirements") or {}).get("mfg_part_number")
        if expected_mfg is None:
            if got:
                reasons.append(f"expected no MFG part number, got {got!r}")
        elif not got or _norm(got) != _norm(expected_mfg):
            reasons.append(f"rfq mfg_part_number: got {got!r}, expected {expected_mfg!r}")

    confirmed = case.get("expected_mfg_confirmed")
    quote = result.get("supplier_quote")
    if confirmed is not None and quote is not None:
        quoted = quote.get("mfg_part_number")
        matches = bool(quoted and expected_mfg not in (None, "__skip__")
                       and _norm(quoted) == _norm(expected_mfg))
        if confirmed and not matches:
            reasons.append(f"expected supplier to confirm {expected_mfg!r}, got {quoted!r}")
        if not confirmed and matches:
            reasons.append(f"expected a substitute MFG part number, but supplier matched {quoted!r}")
        if not confirmed and not quoted:
            reasons.append("expected a substitute MFG part number, but supplier stated none")

    return Grade("mfg", not reasons, "ok" if not reasons else "; ".join(reasons))


def _price(value) -> Decimal | None:
    """Pull a decimal out of '$18.50', 'USD 18.50/pc', '1,050' etc.

    Grades the number, not the formatting — an extraction is not wrong for
    writing 'USD 18.50' where the label says '18.50'.
    """
    if value is None:
        return None
    match = re.search(r"\d[\d,]*\.?\d*", str(value))
    if not match:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None


def grade_price_break_values(result: dict, case: dict) -> Grade:
    """Exact per-row check of what was actually quoted.

    The shape graders only ask whether price breaks exist; this asks whether
    they carry the right part number, tier, quantity and unit price. Cases opt
    in with `expected_price_break_rows`; omit the key to skip.
    """
    if "expected_price_break_rows" not in case:
        return Grade("price_break_values", True, "skipped (no labeled rows)")

    def key(part, tier, qty, price):
        return (_norm(part), _norm(tier), _price(qty), _price(price))

    expected = {key(*row) for row in case["expected_price_break_rows"]}
    got = {
        key(pb.get("part_number"), pb.get("service_tier"), pb.get("quantity"), pb.get("unit_price"))
        for pb in (result.get("supplier_quote") or {}).get("price_breaks") or []
    }
    if got == expected:
        return Grade("price_break_values", True, f"all {len(expected)} rows exact")

    def show(rows):
        return ", ".join(f"{p or '?'}{'/' + t if t else ''} {q}@{v}" for p, t, q, v in sorted(
            rows, key=lambda r: (r[0] or "", r[1] or "", r[2] or 0)))

    missing, extra = expected - got, got - expected
    parts = []
    if missing:
        parts.append(f"missing/wrong [{show(missing)}]")
    if extra:
        parts.append(f"unexpected [{show(extra)}]")
    return Grade("price_break_values", False, "; ".join(parts))


GRADERS = [
    grade_classification,
    grade_quote_signals,
    grade_part_numbers,
    grade_missing_fields,
    grade_service_tiers,
    grade_mfg,
    grade_price_break_values,
]


# ── Runner ─────────────────────────────────────────────────────────────────────

def run_case(case: dict) -> CaseResult:
    files = case.get("thread_emails") or [case["email_file"]]
    try:
        messages = [parse_email_file(Path(f)) for f in files]
        result = asdict(process_thread(messages))
    except Exception as exc:  # a crashed case is a failed case, not a dead run
        return CaseResult(case["email_file"], error=f"{type(exc).__name__}: {exc}")
    return CaseResult(case["email_file"], [grader(result, case) for grader in GRADERS])


def run_evals(cases: list[dict], workers: int = DEFAULT_WORKERS) -> list[CaseResult]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_case, cases))


def load_cases(path: Path = DEFAULT_CASE_FILE) -> list[dict]:
    return json.loads(path.read_text())


# ── Reporting ──────────────────────────────────────────────────────────────────

def format_report(results: list[CaseResult]) -> str:
    lines: list[str] = []
    per_grader: dict[str, list[int]] = {g.__name__: [0, 0] for g in GRADERS}

    for res in results:
        if res.error:
            lines.append(f"ERROR  {res.email_file}\n         {res.error}")
            continue
        failures = [g for g in res.grades if not g.passed]
        status = "PASS " if not failures else "FAIL "
        lines.append(f"{status}  {res.email_file}")
        for grade in failures:
            lines.append(f"         {grade.grader}: {grade.reason}")

    for res in results:
        for grade in res.grades:
            counts = per_grader[f"grade_{grade.grader}"]
            counts[1] += 1
            counts[0] += 1 if grade.passed else 0

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    lines.append("")
    lines.append(f"Cases: {passed}/{total} fully passing")
    lines.append("Per grader:")
    for name, (ok, seen) in per_grader.items():
        label = name.removeprefix("grade_")
        bar = "" if seen == 0 else f"  ({100 * ok // seen}%)"
        lines.append(f"  {label:<18} {ok}/{seen}{bar}")
    return "\n".join(lines)


def to_json(results: list[CaseResult]) -> list[dict]:
    return [asdict(r) for r in results]


RUNS_DIR = Path("runs")


def summarize_run(rows: list[dict]) -> dict:
    """Roll a saved run up into dashboard-friendly totals."""
    per_grader: dict[str, dict[str, int]] = {}
    cases = []
    for row in rows:
        grades = row.get("grades") or []
        for grade in grades:
            slot = per_grader.setdefault(grade["grader"], {"passed": 0, "total": 0})
            slot["total"] += 1
            slot["passed"] += 1 if grade["passed"] else 0
        cases.append({
            "email_file": row["email_file"],
            "error": row.get("error"),
            "passed": row.get("error") is None and all(g["passed"] for g in grades),
            "grades": grades,
        })
    return {
        "cases": cases,
        "total": len(cases),
        "passed": sum(1 for c in cases if c["passed"]),
        "per_grader": per_grader,
    }


def _run_path(name: str, runs_dir: Path) -> Path | None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = runs_dir / f"{name}.json"
    return path if path.is_file() else None


def list_runs(runs_dir: Path = RUNS_DIR) -> list[dict]:
    runs = []
    for path in runs_dir.glob("*.json") if runs_dir.is_dir() else []:
        try:
            summary = summarize_run(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
        runs.append({
            "name": path.stem,
            "modified": path.stat().st_mtime,
            "total": summary["total"],
            "passed": summary["passed"],
            "per_grader": summary["per_grader"],
        })
    return sorted(runs, key=lambda r: r["modified"], reverse=True)


def load_run(name: str, runs_dir: Path = RUNS_DIR) -> dict | None:
    path = _run_path(name, runs_dir)
    if path is None:
        return None
    summary = summarize_run(json.loads(path.read_text()))
    summary["name"] = name
    summary["modified"] = path.stat().st_mtime
    return summary


def compare_runs(baseline: list[dict], current: list[CaseResult]) -> str:
    """Diff two runs at the (case, grader) level — the hill-climbing signal."""
    def flatten(rows) -> dict[tuple[str, str], bool]:
        out = {}
        for row in rows:
            email = row["email_file"] if isinstance(row, dict) else row.email_file
            grades = row["grades"] if isinstance(row, dict) else [asdict(g) for g in row.grades]
            for grade in grades:
                out[(email, grade["grader"])] = grade["passed"]
        return out

    before, after = flatten(baseline), flatten(current)
    fixed = sorted(k for k in after if after[k] and not before.get(k, True))
    broken = sorted(k for k in after if not after[k] and before.get(k, False))

    lines = [f"Fixed:  {len(fixed)}", *(f"  + {email}  [{grader}]" for email, grader in fixed),
             f"Broken: {len(broken)}", *(f"  - {email}  [{grader}]" for email, grader in broken)]
    net = len(fixed) - len(broken)
    lines.append(f"Net: {net:+d} checks")
    return "\n".join(lines)
