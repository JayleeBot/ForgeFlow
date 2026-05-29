# ForgeFlow — Agent Capabilities

ForgeFlow is a buyer-side RFQ assistant. The end goal is an **LLM agent** that reads a
procurement inbox, triages and classifies supplier quote emails, extracts structured
pricing/lead-time data without fabricating values, records it, and drafts follow-ups for
anything missing — leaving the send decision to a human.

This document lists the core capabilities and their current implementation status.

## Status legend

- **Done** — implemented and working end-to-end.
- **Partial** — works, but via the regex/rule-based prototype, not the intended agent.
- **Not started** — required for the agent goal, not yet built.

> **Headline:** every capability below has a working *regex/rule-based* implementation, and
> the full pipeline runs end-to-end (`init` → `sync` → `list-cases`/`list-drafts` → `send`).
> What does **not** exist yet is the **agent (LLM) layer** — the actual goal. There is no
> model call anywhere in the codebase today; classification, extraction, and drafting are all
> regex and static templates.

## 1. Ingest & understand

| Capability | Status | Notes |
|---|---|---|
| Read incoming mail (local `.eml`) | Done | `LocalMailbox` + `parser.py` |
| Read incoming mail (Outlook / MS Graph) | Done | `OutlookMailbox`; fetch + sendMail wired, token from env |
| Thread awareness | Done | `thread_id` = hash of normalized-subject + sender |
| Clean & normalize body | Done | strips quoted replies, signatures, HTML |

> Known bug: `config.py` points `inbox_dir` at `data/sample_inbox`, but the fixtures live in
> `data/sample_emails`. `sync` reads an empty folder out of the box until this is fixed.

## 2. Triage & classify

| Capability | Status | Notes |
|---|---|---|
| Classify thread (quote_received / supplier_followup / ignore) | Partial | keyword-hint matching in `extractor._classify`, not reasoning |
| `quote_incomplete` classification | Partial | currently derived as a *status* in `workflow.py`, not a true class |
| Reason over content (LLM) | Not started | the agent goal — replaces keyword hints |

## 3. Extract structured data

| Capability | Status | Notes |
|---|---|---|
| Price breaks, PLT, long-lead parts, MOQ, payment terms, NRE, COO | Partial | regex in `extractor.py`; brittle on novel formats |
| Missing-field detection | Done | `_derive_missing_fields` flags absent unit_price / PLT / payment_terms |
| Grounding guarantee (only emit verbatim values, else null) | Not started | critical for the agent: "not found" must beat "guessed" |
| Per-field confidence signals | Not started | low-confidence extractions should route to human attention |
| LLM structured extraction | Not started | one Claude call per thread → JSON schema (the agent backbone) |

## 4. Report

| Capability | Status | Notes |
|---|---|---|
| Persist cases + fields to SQLite | Done | `cases` table, `upsert_case` |
| Event log / audit trail | Done | `case_events` table, `record_event` on every step |
| Surface results (list-cases / list-drafts) | Done | CLI commands |

## 5. Follow up with the supplier

| Capability | Status | Notes |
|---|---|---|
| Draft follow-up requesting missing fields | Partial | static template in `workflow.build_draft` |
| Draft acknowledgement for supplier follow-ups | Partial | static template |
| Context-aware natural drafting (LLM) | Not started | the agent goal — replaces templates |
| Human-in-the-loop send | Done | drafts persist; nothing sends without `forgeflow send` |

## Cross-cutting

| Capability | Status | Notes |
|---|---|---|
| Provider-agnostic (local ↔ Outlook) | Done | `build_mailbox`, `Mailbox` protocol |
| Evaluable (score against expected results) | Not started | `data/eval_cases/eval_cases.json` exists; no runner reads it |
| Prompts as standalone files | Not started | planned `src/forgeflow/prompts/` folder |

## Summary

- **Plumbing (ingest, store, event log, CLI, both mailbox providers, human-in-the-loop send):** Done.
- **Intelligence (classify, extract, draft):** exists only as a regex/template prototype — **Partial**.
- **The agent itself (LLM extraction with grounding + confidence, LLM drafting, eval harness, prompts folder):** **Not started.**

In short: the skeleton is real and works; the agent brain has not been built yet.
