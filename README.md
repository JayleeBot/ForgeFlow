# ForgeFlow

ForgeFlow is a local-first email assistant for **procurement and sourcing teams**. It monitors a buyer's quote inbox, automatically triages incoming supplier responses, extracts structured pricing and lead time data, and drafts follow-up emails when key information is missing.

## The problem it solves

When a buyer sends RFQs to multiple suppliers, the responses come back in unstructured email form — varying formats, missing fields, inconsistent terminology. Reviewing each response manually is time-consuming and error-prone. ForgeFlow automates the triage layer so buyers can focus on decision-making rather than inbox management.

## What ForgeFlow extracts from supplier quote emails

- **Price breaks** — e.g. `100@$24.00, 500@$18.00, 1000@$15.00`
- **Production lead time** — e.g. `8 weeks`
- **Long lead time components** — part numbers with lead time ≥ 8 weeks
- **MOQ** — minimum order quantity if stated
- **Payment terms** — e.g. `Net 30`
- **NRE** — non-recurring engineering cost if applicable
- **COO** — country of origin (relevant for landed cost comparison)
- **Missing fields** — flags what needs to be followed up with the supplier

## Quote classification

Each supplier email thread is classified into one of:

| Classification | Meaning |
|---|---|
| `quote_received` | Supplier sent a complete quote |
| `quote_incomplete` | Quote received but key fields are missing |
| `supplier_followup` | Supplier is following up on a previously sent quote |
| `ignore` | Not actionable |

## Draft generation

When a quote is incomplete, ForgeFlow automatically drafts a follow-up email to the supplier requesting the missing information. Buyers review and approve before sending.

## Project structure

```
src/forgeflow/         # core app code
data/sample_emails/    # 5 sample supplier quote emails for testing
data/eval_cases/       # evaluation test cases with expected extraction results
data/outbox/           # local sent-output directory
data/forgeflow.db      # SQLite database (created at runtime)
docs/                  # workflow and setup documentation
```

## Quick start (local mode)

```bash
PYTHONPATH=src python3 -m forgeflow.cli init
PYTHONPATH=src python3 -m forgeflow.cli sync
PYTHONPATH=src python3 -m forgeflow.cli list-cases
PYTHONPATH=src python3 -m forgeflow.cli list-drafts
```

Send a draft reply to a supplier:

```bash
PYTHONPATH=src python3 -m forgeflow.cli send <thread_id>
```

## Outlook mode

ForgeFlow connects to a real Outlook mailbox via Microsoft Graph.

Required environment variables:

```bash
export FORGEFLOW_OUTLOOK_ACCESS_TOKEN="..."
export FORGEFLOW_OUTLOOK_MAILBOX="quotes@yourcompany.com"
```

Run with `--provider outlook`:

```bash
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook sync
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook list-cases
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook list-drafts
```

See `docs/microsoft_graph_setup.md` for full setup instructions.

## How it works

1. Emails are ingested from local `.eml` files or Outlook via Microsoft Graph
2. Each thread is classified by quote status
3. Structured fields are extracted using regex-based parsing
4. Cases and extracted data are persisted in SQLite
5. If key fields are missing, a draft follow-up is generated for buyer review
6. Buyer approves and sends via `forgeflow send`

## Roadmap

- [ ] Automated supplier follow-up when RFQ due date is approaching (Issue #4)
- [ ] LLM-assisted extraction for unstructured quote formats
- [ ] Attachment parsing (Excel/PDF quote sheets)
- [ ] Multi-supplier comparison view
- [ ] Scheduled sync and follow-up reminders
- [ ] Full OAuth flow for production Outlook integration
