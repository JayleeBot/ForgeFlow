# ForgeFlow Project Status

> Reference document for Claude (quick project orientation) and for the user (pending work).
> Update after major changes.
> Last updated: 2026-06-05

---

## What It Does

ForgeFlow is a local-first procurement email assistant. When a supplier replies to an RFQ,
the agent automatically:
1. Parses the email (price breaks, lead time, payment terms, NRE, COO, etc.)
2. Determines whether the quote is complete
3. Drafts follow-up emails (chase missing fields, or flag buyer for a decision)

---

## Code Map

```
src/forgeflow/
├── extractor.py   # Regex extraction — classifies and parses email into ExtractedCase
├── agent.py       # LLM extraction — same contract as extractor, uses Claude API
├── workflow.py    # Business logic — decide_next_action() + build_draft()
├── engine.py      # Orchestration — sync() ingests emails, send() dispatches drafts
├── store.py       # SQLite persistence
├── config.py      # Env-var config (FORGEFLOW_AGENT_EMAIL, FORGEFLOW_FOLLOWUP_RETRY_DAYS)
├── models.py      # Data models (QuoteCase, EmailMessage, Draft)
└── cli.py         # CLI entry point
```

---

## Core Logic: Three-State Model

Each supplier email is extracted and then routed by `workflow.py`:

```
Email arrives
    ↓
extractor / agent extracts fields → ExtractedCase
    ↓
decide_next_action()
    ├── classification = "ignore"              → no action         (status: closed)
    ├── classification = "supplier_reminder"   → draft acknowledgement (status: needs_review)
    ├── missing_fields = ["buyer_input_required"]
    │   └── supplier asked buyer a question    → FLAG FOR BUYER    (status: pending_buyer_input)
    ├── missing_fields not empty               → chase supplier    (status: quote_incomplete)
    └── missing_fields empty                   → quote complete    (status: quote_received)
```

**Key distinction:**
- `classification` = what type of email this is (from extractor)
- `status` = what to do next (from workflow)

---

## Implemented Features

| Feature | Status |
|---------|--------|
| Regex extraction (extractor.py) | Done |
| LLM extraction (agent.py, Claude API) | Done |
| Three-state workflow (workflow.py) | Done |
| Supplier blocking question detection → FLAG FOR BUYER | Done |
| 3-day followup retry throttle | Done |
| Buyer reply detection (exclusion logic) | Done |
| Agent email footer (include agent on all replies) | Done |
| Edge case: quantity-adjusted quotes treated as complete | Done |
| Edge case: supplier blocking question → buyer_input_required | Done |
| Thread-aware extraction (classify on latest, extract from full thread) | Done |
| Python eval — 16 test cases (regex path) | Done — 16/16 passing |
| Promptfoo eval — 16 test cases (LLM path) | Done — 16/16 passing |

---

## Pending TODOs

### High Priority

- [ ] **Commit all changes** — 15 modified files + STATUS.md (untracked):
  - src/forgeflow/{extractor,agent,workflow,engine,store,config,models,cli}.py
  - data/eval_cases/eval_cases.json
  - promptfoo/{provider,tests}.py + src/forgeflow/evaluate.py
  - README.md, docs/agent_capabilities.md, STATUS.md

### Medium Priority

- [ ] **Set FORGEFLOW_AGENT_EMAIL env var** — without it, the footer email address is blank.
  Add to `.env`: `FORGEFLOW_AGENT_EMAIL=forgeflow-agent@electester.com`

### Low Priority (Future)

- [ ] Add more edge case eval scenarios: wrong part number, currency mismatch, partial BOM quotes
- [ ] Decide whether `quote_validity` should be a tracked extraction field
- [ ] Do a full visual review of Promptfoo results from the buyer's perspective

---

## How to Run Evals

```bash
# Python eval (fast, regex path)
cd /Users/jaylee/Desktop/ForgeFlow
PYTHONPATH=src python3 -m forgeflow.cli eval

# Promptfoo eval (slower, LLM path, generates web UI)
PYTHONPATH=src npx promptfoo@latest eval --no-cache

# View last Promptfoo results in browser
npx promptfoo@latest view
# Then open http://localhost:15500
```
