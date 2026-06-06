# ForgeFlow — Agent Capabilities

ForgeFlow is a buyer-side RFQ assistant. The goal is an **LLM agent** that reads a
procurement inbox, triages and classifies supplier quote emails, extracts structured
pricing and lead-time data without fabricating values, records it, and drafts follow-ups
for anything missing — leaving the send decision to a human.

## Status legend

- **Done** — implemented and tested end-to-end.
- **Partial** — works, but limited in scope or robustness.
- **Not started** — required for the full agent vision, not yet built.

## 1. Ingest & understand

| Capability | Status | Notes |
|---|---|---|
| Read incoming mail (local `.eml`) | Done | `LocalMailbox` + `parser.py` |
| Read incoming mail (Outlook / MS Graph) | Done | `OutlookMailbox`; fetch + sendMail wired, token from env |
| Thread awareness | Done | groups emails by normalized subject + sender; full thread context passed to extraction |
| Clean & normalize body | Done | strips quoted replies, signatures, HTML |

## 2. Triage & classify

| Capability | Status | Notes |
|---|---|---|
| Classify email thread (`quote_received` / `supplier_reminder` / `ignore`) | Done | dual-path: keyword-hint matching in `extractor._classify` (fast) and LLM reasoning via `agent.py` (production) |
| Classify on latest email only, extract fields from full thread | Done | `extractor.extract_case` uses `latest_lower` for classification, `combined_text` for field extraction — prevents buyer RFQ text from polluting supplier quote classification |
| Three-state quote status model | Done | `quote_incomplete` → `pending_buyer_input` → `quote_received`; derived in `workflow.decide_next_action` |
| Supplier blocking-question detection | Done | regex in `extractor._detect_supplier_question`; overrides missing_fields to `["buyer_input_required"]` and routes to buyer flag instead of supplier follow-up |

## 3. Extract structured data

| Capability | Status | Notes |
|---|---|---|
| Price breaks, PLT, long-lead parts, MOQ, payment terms, NRE, COO | Done | dual-path: regex in `extractor.py` + LLM structured extraction via `agent.py` (Claude API, tool use) |
| Missing-field detection | Done | `_derive_missing_fields` flags absent unit_price / PLT / payment_terms; clears automatically when quote reference phrases detected |
| Quote completion inference from thread context | Done | when supplier says "as previously quoted", fields are resolved from earlier emails in the combined thread text |
| Edge case: quantity-adjusted quotes | Done | supplier quoting at box-qty or MOQ multiples with explanation treated as complete price breaks |
| Grounding guarantee (verbatim values only) | Done | Promptfoo `check_grounding` assertion verifies all emitted numbers appear verbatim in the thread text |
| Per-field confidence signals | Not started | low-confidence extractions should route to human attention |

## 4. Report & persist

| Capability | Status | Notes |
|---|---|---|
| Persist quote cases + fields to SQLite | Done | `cases` table, `upsert_case` |
| Track followup timing | Done | `last_followup_sent_at` + `followup_count` on `QuoteCase`; used for 3-day retry throttle |
| Event log / audit trail | Done | `case_events` table, `record_event` on every state change |
| Surface results (list-cases / list-drafts) | Done | CLI commands |

## 5. Follow up with the supplier

| Capability | Status | Notes |
|---|---|---|
| Draft follow-up requesting only missing fields | Done | `workflow.build_draft` with targeted field list |
| Draft acknowledgement for supplier reminders | Done | when supplier chases buyer for response, agent drafts "buyer is reviewing" reply |
| Flag buyer when supplier asks a blocking question | Done | `flag_buyer` action creates dashboard-only notice; not sent to supplier |
| Agent email footer on all outbound drafts | Done | "Please ensure {agent_email} is CC'd on all replies" appended to every supplier-facing draft |
| 3-day followup retry | Done | `engine._should_create_draft` throttles re-drafts; `mark_followup_sent` updates timestamp on send |
| Buyer reply detection (unblocks pending_buyer_input) | Done | exclusion logic in `engine.sync`: sender not agent_email and not supplier_email is treated as buyer reply |
| Context-aware natural-language drafting (LLM) | Not started | current drafts use static templates; goal is LLM-generated prose |

## 6. Evaluate

| Capability | Status | Notes |
|---|---|---|
| Python eval (regex path) | Done | `forgeflow.evaluate.run_eval`; 16 cases, sub-second runtime |
| LLM eval (Promptfoo) | Done | `npx promptfoo eval`; 16 cases, web UI at localhost:15500 |
| Thread-aware eval | Done | eval cases specify `thread_emails` lists; provider and evaluate.py load full thread |
| Grounding assertion | Done | verifies extracted numbers are verbatim in source text |
| Edge case coverage | Done | quantity-adjusted quotes, MOQ-adjusted quotes, supplier blocking questions, multi-round RFQ threads |

## 7. Architecture (not yet built)

| Capability | Status | Notes |
|---|---|---|
| CC trigger: derive supplier list + required fields from buyer outbound RFQ | Not started | currently requires manual field definition |
| Per-RFQ required-field spec | Not started | today all RFQs use the same global required fields |
| Cross-round field merge | Partial | thread context passed to extraction, but no explicit fill-gaps-across-rounds merge step |
| Decision dashboard (compare suppliers, landed cost, MOQ trade-offs) | Not started | the end-state UI |
| Attachment parsing (Excel / PDF quote sheets) | Not started | |
| Multi-supplier comparison view | Not started | |

## Summary

The complete extraction-to-draft pipeline is implemented and tested end-to-end via both a
fast regex path and a production LLM path (Claude API with tool use). The eval harness
covers 16 cases including multi-round RFQ threads, edge cases, and grounding verification.

What remains is the upstream (CC trigger, per-RFQ field specs) and downstream (decision
dashboard, supplier comparison) layers, and replacing the static draft templates with
LLM-generated prose.
