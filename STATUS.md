# ForgeFlow Project Status

> Reference document for Claude (quick project orientation) and for the user (pending work).
> Update after major changes.
> Last updated: 2026-10-11

---

## What It Does

ForgeFlow is a procurement email assistant. The buyer CCs it on outbound RFQs; when a
supplier replies, the agent:
1. Parses the email (price breaks, lead time, payment terms, NRE, COO, etc.)
2. Determines whether the quote is complete against the buyer's RFQ requirements
3. Drafts (or, with autosend on, sends) a follow-up for only the missing fields, or flags
   the buyer when the supplier asked a question only the buyer can answer

---

## Code Map

```
butterbase/                  # Production path (forgeflow.butterbase.dev)
├── functions/scan.ts        # Cron every 10 min: one unseen Outlook thread per run →
│                            #   managed-agent session → comparison table + reply
├── functions/rfqs.ts        # Dashboard read function
├── dashboard/               # React buyer dashboard (deploy-time snapshot; demo mode)
├── schema.json              # rfqs, supplier_quotes, quote_price_breaks, interactions, agent_seen
└── deploy*.py, set-secrets.py, push-rotated-token.py

src/forgeflow/               # Python: agent definition, evals, local CLI
├── managed_agent.py         # Coordinator + subagent managed-agent deployment, tool schemas
├── prompts/                 # coordinator.txt, extraction.txt, response.txt, reply_agent.txt
├── agent.py                 # Local agent path (schema, extraction, action state)
├── processor.py             # Local ingest → process → respond loop
├── evals.py                 # Native eval harness over data/eval_cases/eval_cases.json
├── graph.py / auth.py       # Microsoft Graph mailbox + device-code login
├── store.py                 # Local SQLite (data/forgeflow.db)
├── server.py / simulator.py # Local dashboard + scenario simulator
└── cli.py                   # CLI entry point
```

The old regex pipeline (`extractor.py`, `workflow.py`, `engine.py`) has been removed.

---

## Core Logic

The coordinator classifies the latest email in a thread:

- `rfq_sent` — buyer's outbound RFQ → records the RFQ's collection form (`rfq_requirements`)
- `supplier_quote` / `supplier_reminder` → extracts the quote, records it, then either
  chases the supplier for missing required fields or flags the buyer (`blocking_question`)
- `ignore` — everything else

Sending is gated by `FORGEFLOW_MANAGED_AGENT_AUTOSEND`; with it off, the reply text is stored
in `interactions.draft_reply` and nothing is sent.

**Known gap:** the pipeline only reacts to new inbound mail. A supplier who never replies
triggers nothing — see issue #4 below.

---

## Pending TODOs

### High Priority

- [ ] **Issue #4 — follow up suppliers who have not replied by the RFQ due date.**
  Decided 2026-10-11. Implemented on branch `issue-4-rfq-followup`, not yet deployed
  (needs schema apply, managed-agent prompt deploy, function deploy):
  - Extract `response_due_date` from the buyer's RFQ into `rfq_requirements`; store on `rfqs`.
  - Trigger: 2 business days before the due date; on the due date if the RFQ went out with
    less than 2 business days left; no due date → 3 business days after the RFQ was sent.
  - Skip when the supplier has already replied (match on email domain).
  - Deterministic check in a new daily Butterbase function, fixed template (no LLM), a
    `rfq_followups` table so each supplier is chased once.
  - Delivery follows the existing autosend switch (send when on, store draft when off).
  - Usually one supplier per RFQ email.
  - Issue #5 (deliver drafts to the Outlook Drafts folder) is not part of this round.

### ForgeFlow Improvement

- [ ] **Buyer attribution for team-shared CC** — one CC address serves a whole team; each RFQ record
  stores which buyer owns it (from the RFQ email's From address). Scope: `buyer_email` field on the
  RFQ record + dashboard column + filter by buyer. Explicitly out of scope for now: login/accounts,
  per-buyer visibility isolation, roles, seat billing enforcement. (Discussed 2026-07-19 during YC
  application prep; supports the "land one buyer → expand to team" story.)
- [ ] Dashboard Stage B — see `docs/dashboard_stage_b.md`.

### Low Priority (Future)

- [ ] Add more edge case eval scenarios: wrong part number, currency mismatch, partial BOM quotes
- [ ] Decide whether `quote_validity` should be a tracked extraction field

---

## How to Run Evals

```bash
cd /Users/jaylee/Desktop/ForgeFlow
PYTHONPATH=src python3 -m forgeflow.cli eval
```
