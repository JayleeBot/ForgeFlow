# Buyer Dashboard — Stage B Ideas

Stage A is the buyer dashboard in `butterbase/dashboard/`, deployed to
`forgeflow-rfq.butterbase.dev`. It is read-only and renders a data snapshot
baked in at deploy time. This file collects what was deliberately left out of
Stage A, with the reason each one was deferred, so the next round starts from
the buyer's actual needs rather than from scratch.

## Stage A, for reference

A buyer logging in should first see whose move it is, then find a part and
compare suppliers across it at a glance.

- **Home:** three buckets, counted per supplier quote: *Ready for review*,
  *Needs your input*, *Agent working*. The last splits into on track / due soon /
  overdue against a 3-business-day follow-up window.
- **Ready for review:** grouped by part number.
- **Part view:** one row per supplier, with the service tier (Quick Turn,
  Standard…) on the row, quantity breaks as columns, and lead time normalised to
  days.
- **Agent working:** who is holding things up, when the last follow-up went
  out, and how long is left.

## Stage B

### 1. Price history: same part, same supplier, over time

> "For the same part, last year the supplier quoted one price and this year
> another. I want to see how that changed."

**What the buyer wants.** On the part view, each supplier's price for that part
over time, for example `Delta · Mar 2025 $44.10 → Aug 2026 $37.25 (−15%)`. That
shows whether a supplier is trending up, and gives leverage in negotiation.

**Why it isn't in Stage A.** The data doesn't exist yet:

- `scan.ts` upserts `supplier_quotes` on `(rfq_id, supplier_email)` and
  **deletes** that quote's `quote_price_breaks` before re-inserting them. Every
  negotiation round overwrites the previous one.
- History survives only when the same part was quoted on a *different* RFQ
  thread, which is rare in the current data.
- Quotes from before ForgeFlow (last year's) were never ingested.

**What it needs.**

- An append-only `quote_history` table, for example
  `(id, part_number, supplier_email, service_tier, quantity, unit_price,
  lead_time_days, quoted_at, rfq_id, message_id)`. `scan.ts` writes to it on
  every extraction, alongside the current-state tables, which keep driving the
  "latest" view.
- Optionally, a one-off import of historical quotes (a spreadsheet or past
  emails) so the view isn't empty on day one.
- UI: a small per-supplier price line on the part view. Compare the same tier
  and quantity break only, never a Quick Turn price against a Standard one.

### 2. Acting on overdue follow-ups

Stage A only *flags* a follow-up as overdue. The Butterbase pipeline has no rule
that re-chases a supplier once the 3-business-day window lapses.

- Server side: a cron check in `scan.ts`, or a separate function, that drafts or
  sends a second follow-up on overdue quotes.
- Dashboard: a "Send follow-up now" button on the Agent working view.

This is a write action, so it depends on item 4.

### 3. Live data instead of a deploy-time snapshot

Today the page shows data as of its last deploy, and the follow-up countdown is
computed against the browser's clock from that snapshot. Reading live needs
end-user auth on the Butterbase app, which is currently unavailable (see
`butterbase/README.md`, "Known gaps"). A scheduled redeploy would be a cheap
interim step.

### 4. Buyer write actions

Approving a draft reply, answering a supplier's question from the dashboard,
and marking a quote as awarded or rejected. Each needs authenticated writes
(item 3).

### 5. Smaller items

- CSV export of a part's comparison table, for Excel.
- A long-lead-time alert: lead time over 12 weeks (84 days), per
  `docs/buyer_rfq_review_workflow.md`.
