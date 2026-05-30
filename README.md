# ForgeFlow

ForgeFlow is a local-first email assistant for **procurement and sourcing teams**. It monitors a buyer's quote inbox, automatically triages incoming supplier responses, extracts structured pricing and lead time data, and drafts follow-up emails when key information is missing.

## The problem it solves

When a buyer sends RFQs to multiple suppliers, the responses come back in unstructured email form — varying formats, missing fields, inconsistent terminology. Reviewing each response manually is time-consuming and error-prone. ForgeFlow automates the triage layer so buyers can focus on decision-making rather than inbox management.

## System architecture

ForgeFlow is an **LLM agent (Claude)** that turns a buyer's RFQ inbox into a self-driving qualification loop. The defining idea: **requirements are per-RFQ**. The buyer's own RFQ defines which fields matter for that RFQ — RFQ-1 might need `{unit price, MOQ, lead time, COO}` while RFQ-2 only needs `{price, material}`. The agent chases **only that RFQ's** missing fields, across however many email rounds it takes, and notifies the buyer the moment that specific set is satisfied — never a fixed "collect everything" checklist.

```mermaid
flowchart TB
    subgraph IN["Inputs"]
        BUYER["Buyer's RFQ email<br/>defines required fields per RFQ"]
        SUP["Supplier replies<br/>price, MOQ, lead time, ..."]
    end
    subgraph ING["Ingest"]
        MBX["Mailbox<br/>Outlook / Graph or local .eml"]
        PARSE["Parser<br/>clean body, thread linkage"]
    end
    subgraph AGENT["Agent core (Claude)"]
        REQ["Derive RFQ requirement spec<br/>from buyer email"]
        EX["Extract fields from reply<br/>grounded: verbatim-or-null"]
        MERGE["Merge into quote state<br/>fill gaps, detect conflicts"]
        CHK["Completion check + decision flags<br/>vs RFQ.required_fields and thresholds"]
    end
    subgraph DB["State (SQLite)"]
        RFQDB[("RFQ + required_fields")]
        SQDB[("SupplierQuote field_state")]
        EV[("Event log")]
    end
    subgraph HITL["Human-in-the-loop"]
        DRAFT["Draft follow-up<br/>only the missing required fields"]
        DASH["Dashboard: review / approve / send"]
    end
    NOTIFY(["RFQ ready to review (+ flags)"])
    COMPARE["Multi-supplier comparison<br/>landed cost, lead time, MOQ, tariff"]

    BUYER --> MBX
    SUP --> MBX --> PARSE --> EX --> MERGE --> CHK
    MBX --> REQ --> RFQDB --> CHK
    MERGE --> SQDB
    MERGE --> EV
    CHK -->|outstanding| DRAFT --> DASH --> MBX
    CHK -->|satisfied| NOTIFY --> COMPARE
```

**Layers**

- **Ingest** — reads supplier replies (and the buyer's RFQ) from Outlook/Graph or local `.eml`, cleans them, and links each email to its RFQ + supplier thread.
- **Agent core (Claude)** — derives the per-RFQ requirement spec from the buyer's email; extracts fields from each supplier reply with a strict *verbatim-or-null* grounding rule; merges them into a running quote record; checks completion and raises decision flags.
- **State (SQLite)** — the RFQ + its `required_fields`, the per-supplier `field_state` that accumulates across rounds, and an append-only event log for audit.
- **Human-in-the-loop** — targeted follow-up drafts (only the missing required fields) that the buyer reviews and approves in the dashboard; nothing sends without approval.
- **Outputs** — a "ready to review" notification when the RFQ's required set is satisfied, and a multi-supplier comparison that weighs more than price (landed cost incl. tariff by COO, lead time, MOQ feasibility).

### How the agent works (per supplier reply)

```mermaid
flowchart TD
    R(["Supplier reply"]) --> M["Map to RFQ + supplier"]
    M --> E["Extract fields (grounded)"]
    E --> U["Merge into SupplierQuote.field_state<br/>fill outstanding, detect conflicts, keep provenance"]
    U --> K["Evaluate vs RFQ.required_fields<br/>+ run decision flags"]
    K --> D{"Required set<br/>satisfied?"}
    D -- No --> F["Draft follow-up<br/>only outstanding required fields"]
    F --> A["Buyer approves in dashboard"]
    A --> S["Send"]
    S -. next reply .-> R
    D -- Yes --> N(["Notify: RFQ ready to review"])
```

The agent's **goal state** is "satisfy this RFQ's required set." That single objective drives the targeted follow-ups, prevents re-asking answered fields, and decides when to stop — all scoped to the individual RFQ. It also flags hidden-cost traps a price-only view misses (e.g. *MOQ 10,000 when you need 100*, or a 52-week lead time on the cheapest quote).

> **Status:** Claude extraction, the grounded eval (Promptfoo), and human-in-the-loop drafting/send are implemented. Per-RFQ requirement specs, cross-round state merge, and multi-supplier comparison are the in-progress architecture shown above.

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
2. The buyer's RFQ defines the required-field spec for that RFQ
3. Claude extracts structured fields from each supplier reply (grounded: only values present in the email)
4. Fields are merged into a running per-supplier quote record across multiple reply rounds
5. Completion is checked against that RFQ's required fields; decision flags (MOQ vs needed qty, long lead time, COO/tariff) are raised
6. If required fields are still missing, a targeted follow-up is drafted (only the gaps) for buyer approval, and the loop continues on the next reply
7. When the RFQ's required set is satisfied, the buyer is notified that it's ready to review

## Roadmap

- [ ] Automated supplier follow-up when RFQ due date is approaching (Issue #4)
- [ ] LLM-assisted extraction for unstructured quote formats
- [ ] Attachment parsing (Excel/PDF quote sheets)
- [ ] Multi-supplier comparison view
- [ ] Scheduled sync and follow-up reminders
- [ ] Full OAuth flow for production Outlook integration
