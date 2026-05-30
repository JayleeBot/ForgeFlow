# Buyer RFQ Review Workflow for ForgeFlow

## Business Context

In electronics procurement, buyers regularly send Request for Quotation (RFQ) emails to multiple suppliers for components such as PCBs, ICs, connectors, and passive components. Managing supplier responses manually is time-consuming and error-prone.

Common pain points in real-world RFQ workflows:

- **Incomplete supplier responses**: Suppliers frequently omit critical fields such as MOQ, lead time, or unit price, requiring buyers to send follow-up emails manually.
- **Hidden long lead time parts**: In a multi-line BOM, one or two components with 20+ week lead times can delay an entire production run. These are easy to miss when reviewing responses manually.
- **No NRE breakdown**: Suppliers sometimes quote a total price without separating NRE (Non-Recurring Engineering) costs from unit price, making it impossible to compare quotes accurately across vendors.
- **Quote validity not stated**: Without a validity date, a quoted price may no longer be honored by the time a PO is issued.

ForgeFlow is designed to act as a **buyer-side assistant** that monitors supplier responses and flags these issues automatically.

---

## Core Workflow

### Step 1: Buyer sends RFQ

The buyer sends an RFQ email to one or more suppliers. The RFQ typically includes:

- Part number(s)
- Description
- Target quantity (or quantity breaks)
- Required delivery date
- BOM attachment (optional)

### Step 2: Supplier responds

The supplier replies with a quote. ForgeFlow monitors the buyer's inbox (via Microsoft Graph / Outlook) and detects incoming supplier quote responses.

### Step 3: ForgeFlow analyzes the supplier response

ForgeFlow extracts and validates the following fields from each supplier response:

| Field | Required | Notes |
|-------|----------|-------|
| Unit price | ✅ | Per-unit cost at quoted quantity |
| MOQ | ✅ | Minimum order quantity |
| Lead time | ✅ | Standard production lead time in weeks |
| NRE cost | ⚠️ | Required if tooling or setup is involved |
| Quote validity date | ⚠️ | Date until which the price is guaranteed |
| Long lead time flag | ✅ | Any component with lead time > 12 weeks |
| Part number confirmation | ✅ | Supplier confirms the correct part |

### Step 4: ForgeFlow flags missing or incomplete information

If any required field is missing, ForgeFlow generates a structured summary:

```
Supplier: supplier@example.com
Thread: Re: RFQ - Connector Part #CX-4402

Missing fields detected:
- MOQ not stated
- Quote validity date not provided

Long lead time alert:
- Part #CX-4402: Lead time = 20 weeks (threshold: 12 weeks)

Suggested action: Send follow-up requesting MOQ and validity date.
```

### Step 5: ForgeFlow drafts a follow-up email

ForgeFlow generates a draft follow-up to the supplier requesting only the missing fields. The buyer reviews the draft in the dashboard and sends it.

### Step 6: ForgeFlow monitors the follow-up response

After the follow-up is sent, ForgeFlow continues to monitor the inbox for the supplier's next reply. When a new reply arrives, ForgeFlow repeats Steps 2–5:

- Re-reads the supplier reply
- Re-extracts all fields
- Checks again for any remaining missing information
- Drafts another follow-up if gaps remain

This loop continues until all required fields are present.

### Step 7: Buyer notification — RFQ ready to review

Once all required fields are confirmed complete, ForgeFlow sends the buyer a notification:

```
RFQ1234 is ready to review.
All required fields received: unit price, MOQ, lead time, NRE, validity date, part number confirmation.
```

The buyer can then open the dashboard to review the full quote summary and decide next steps (issue PO, compare suppliers, negotiate).

### Step 8: BOM-level lead time analysis (planned)

When a buyer uploads a BOM, ForgeFlow cross-references all quoted lead times against the BOM line items and identifies:

- Which parts are on the critical path
- Which parts have no quote received yet
- Which parts exceed acceptable lead time thresholds

---

## Key Field Definitions

**MOQ (Minimum Order Quantity)**
The smallest quantity a supplier will accept per order. Critical for cost planning and inventory strategy.

**Lead Time**
The number of weeks from PO placement to delivery. For electronics, standard lead times range from 4–16 weeks. Anything above 12 weeks is considered a long lead time part and requires early procurement action.

**NRE (Non-Recurring Engineering)**
One-time setup or tooling cost charged by the supplier. Must be separated from unit price to enable accurate quote comparison.

**Long Lead Time Part**
Any component in the BOM with a supplier-quoted lead time exceeding 12 weeks. These parts define the earliest possible production start date and must be identified and ordered first.

**Quote Validity**
The expiration date of a quoted price. After this date, the supplier may reprice. Buyers should issue POs before validity expires or request re-quotation.

---

## Why This Matters

Manual review of supplier responses across a multi-line BOM is slow and inconsistent. A buyer managing 50+ active RFQs cannot reliably catch every missing MOQ or flag every long lead time part by reading emails one by one.

ForgeFlow automates this triage layer, ensuring:

- No missing fields are overlooked
- Long lead time parts are surfaced immediately
- Follow-up drafts are ready without manual writing
- The buyer is notified only when a quote is truly complete and ready to act on
- All quote activity is logged in a structured database for audit and analysis
