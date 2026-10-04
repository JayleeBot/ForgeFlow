import type {
  Extracted,
  Message,
  PriceBreak,
  QuoteCore,
  Rfq,
  RfqRequirements,
  Run,
  Snapshot,
  SupplierQuote,
} from "./types";

declare global {
  interface Window {
    __FORGEFLOW_SNAPSHOT__?: Snapshot;
  }
}

/**
 * The snapshot is baked into index.html at deploy time by deploy-frontend.py,
 * which holds the service key. In local dev there is no bake, so fall back to
 * /snapshot.json — written by `deploy-frontend.py --snapshot-only` and
 * gitignored, because it holds real supplier data.
 */
export async function loadSnapshot(): Promise<Snapshot> {
  if (window.__FORGEFLOW_SNAPSHOT__) return window.__FORGEFLOW_SNAPSHOT__;
  const res = await fetch("/snapshot.json", { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`No baked snapshot, and /snapshot.json returned HTTP ${res.status}`);
  return (await res.json()) as Snapshot;
}

// ── Reading the agent's extraction ───────────────────────────────────────────

/** The agent nests its payload under `supplier_quote`; tolerate a flat shape too. */
export function coreOf(extracted: Extracted | QuoteCore | null | undefined): QuoteCore {
  if (!extracted) return {};
  const nested = (extracted as Extracted).supplier_quote;
  return (nested || (extracted as QuoteCore)) ?? {};
}

export function requirementsOf(rfq: Rfq): RfqRequirements {
  if (rfq.collection_form) return rfq.collection_form;
  for (const quote of rfq.supplier_quotes ?? []) {
    const reqs = (quote.extracted as Extracted | null)?.rfq_requirements;
    if (reqs) return reqs;
  }
  return {};
}

export function priceRows(core: QuoteCore): PriceBreak[] {
  const breaks = core.price_breaks;
  // Recorded as an array of {quantity, unit_price, lead_time, part_number, service_tier}.
  if (Array.isArray(breaks)) return breaks;
  // Tolerate a {tier: {qty: price}} map as well.
  if (breaks && typeof breaks === "object") {
    const rows: PriceBreak[] = [];
    for (const [service_tier, qtys] of Object.entries(breaks)) {
      if (qtys && typeof qtys === "object") {
        for (const [quantity, unit_price] of Object.entries(qtys as Record<string, unknown>)) {
          rows.push({ service_tier, quantity, unit_price: unit_price as string | number });
        }
      }
    }
    return rows;
  }
  return [];
}

/**
 * The agent records {per_part: [...], quote_level: [...]}, where quote_level
 * holds bare field names and per_part holds {missing, part_number, service_tier}
 * objects. Flattened to one list of readable strings, keeping the part and tier
 * a field is missing on — "unit_price" alone would not tell a buyer which line
 * to chase. A plain array is tolerated too, which is what older rows hold.
 */
export function missingOf(core: QuoteCore, quote: SupplierQuote): string[] {
  const flatten = (value: unknown): string[] => {
    if (typeof value === "string") return value ? [value] : [];
    if (Array.isArray(value)) return value.flatMap(flatten);
    if (value && typeof value === "object") {
      const entry = value as Record<string, unknown>;
      if (typeof entry.missing === "string") {
        const where = [entry.part_number, entry.service_tier].filter(Boolean).join(" · ");
        return [where ? `${entry.missing} (${where})` : entry.missing];
      }
      return Object.values(entry).flatMap(flatten);
    }
    return [];
  };
  return flatten(core.missing_fields ?? quote.missing_fields);
}

/**
 * Only a comma with exactly three digits behind it is a thousands separator.
 * Stripping every comma turns the European "3,00" into 300 — a hundredfold
 * price error on a figure a buyer is about to compare suppliers on.
 * Mirrors priceToNumber in functions/scan.ts.
 */
export function priceToNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const m = value.replace(/,(?=\d{3}(\D|$))/g, "").match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
}

/**
 * A buyer choosing between "24 weeks" and "25 business days from PO" needs one
 * scale, so both become calendar days, business days at the usual 7/5. A value
 * that names no unit stays null rather than being guessed at.
 * Mirrors leadTimeToDays in functions/scan.ts.
 */
export function leadTimeToDays(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const m = value.match(/(\d+(?:\.\d+)?)\s*(weeks?|business days?|working days?|days?)/i);
  if (!m) return null;
  const n = Number(m[1]);
  const unit = m[2].toLowerCase();
  if (unit.startsWith("week")) return Math.round(n * 7);
  if (unit.startsWith("day")) return Math.round(n);
  return Math.round((n * 7) / 5);
}

export const supplierLabel = (quote: SupplierQuote): string =>
  quote.supplier_name ||
  (coreOf(quote.extracted).supplier_name as string) ||
  quote.supplier_email ||
  "Unknown supplier";

const stripPrefix = (s: string) => s.replace(/^((re|fw|fwd|subject)\s*:\s*)+/i, "").trim();

/** What ties threads together as one RFQ, best available source first. */
export function referenceOf(rfq: Rfq): string {
  for (const quote of rfq.supplier_quotes ?? []) {
    const ref = coreOf(quote.extracted).rfq_reference;
    if (ref) return stripPrefix(String(ref));
  }
  const reqs = requirementsOf(rfq);
  if (reqs.our_part_number) return String(reqs.our_part_number);
  if (reqs.mfg_part_number) return String(reqs.mfg_part_number);
  return stripPrefix(rfq.subject || rfq.id);
}

// ── Follow-up clock ──────────────────────────────────────────────────────────
// A supplier gets FOLLOW_UP_BUSINESS_DAYS to answer the agent's follow-up before
// it counts as overdue. Weekends do not count.

export const FOLLOW_UP_BUSINESS_DAYS = 3;

const isWeekend = (d: Date) => d.getDay() === 0 || d.getDay() === 6;

export function addBusinessDays(from: Date, days: number): Date {
  const d = new Date(from);
  let left = days;
  while (left > 0) {
    d.setDate(d.getDate() + 1);
    if (!isWeekend(d)) left -= 1;
  }
  return d;
}

/** Whole business days from `from` to `to`; negative once `to` has passed. */
export function businessDaysBetween(from: Date, to: Date): number {
  const sign = to >= from ? 1 : -1;
  const [a, b] = sign > 0 ? [from, to] : [to, from];
  const d = new Date(a);
  let n = 0;
  while (true) {
    d.setDate(d.getDate() + 1);
    if (d > b) break;
    if (!isWeekend(d)) n += 1;
  }
  return sign * n;
}

export type ClockStatus = "on_track" | "due_soon" | "overdue";

export type FollowUp = { sentAt: string; due: Date; daysLeft: number; status: ClockStatus };

function followUpClock(sentAt: string, now: Date): FollowUp {
  const due = addBusinessDays(new Date(sentAt), FOLLOW_UP_BUSINESS_DAYS);
  const daysLeft = businessDaysBetween(now, due);
  const status: ClockStatus = now > due ? "overdue" : daysLeft <= 1 ? "due_soon" : "on_track";
  return { sentAt, due, daysLeft, status };
}

// ── One entry per supplier quote ─────────────────────────────────────────────
// The supplier quote is the unit everything is counted in: each one has exactly
// one state, so the home counts never double up. Whose move it is:
//
//   ready        every field is in — the buyer compares and decides
//   needs_input  the supplier asked the buyer something, or the agent drafted a
//                follow-up that is waiting for the buyer to send (autosend off)
//   working      the follow-up went out; the supplier is on the clock

export type QuoteStateKey = "ready" | "needs_input" | "working";

export const BUYER_INPUT = "buyer_input_required";

export type QuoteEntry = {
  key: string;
  quote: SupplierQuote;
  thread: Rfq;
  reference: string;
  supplier: string;
  state: QuoteStateKey;
  /** Why the entry needs the buyer, when state is needs_input. */
  reason: "question" | "approve_draft" | null;
  /** What the supplier still owes, minus the buyer-input marker. */
  missing: string[];
  question: string | null;
  draft: string | null;
  followUp: FollowUp | null;
  quotedAt: string;
};

const runsSent = (runs: Run[]) =>
  runs.filter((r) => r.sent_reply && r.processed_at).map((r) => String(r.processed_at));

export function buildEntries(rfqs: Rfq[], now: Date): QuoteEntry[] {
  // The same supplier can appear on several threads of one RFQ (a resend, a
  // test); keep only their newest quote so they are counted once.
  const newest = new Map<string, { quote: SupplierQuote; thread: Rfq; reference: string }>();
  for (const thread of rfqs) {
    const reference = referenceOf(thread);
    for (const quote of thread.supplier_quotes ?? []) {
      const who = (quote.supplier_email || supplierLabel(quote)).toLowerCase();
      const key = `${reference.toLowerCase()}|${who}|${supplierLabel(quote).toLowerCase()}`;
      const prev = newest.get(key);
      if (!prev || String(quote.updated_at ?? "") > String(prev.quote.updated_at ?? "")) {
        newest.set(key, { quote, thread, reference });
      }
    }
  }

  return [...newest.entries()].map(([key, { quote, thread, reference }]) => {
    const core = coreOf(quote.extracted);
    const all = missingOf(core, quote);
    const asksBuyer = all.some((f) => f.toLowerCase().includes(BUYER_INPUT));
    const missing = all.filter((f) => !f.toLowerCase().includes(BUYER_INPUT));

    const sent = runsSent(thread.runs ?? []).sort();
    const lastSent = sent.length ? sent[sent.length - 1] : null;
    const latest = [...(thread.messages ?? [])].sort((a, b) =>
      String(a.sent_at ?? "").localeCompare(String(b.sent_at ?? "")),
    ).pop();
    const draft = latest?.draft_reply || null;

    let state: QuoteStateKey;
    let reason: QuoteEntry["reason"] = null;
    if (asksBuyer) {
      state = "needs_input";
      reason = "question";
    } else if (!missing.length) {
      state = "ready";
    } else if (lastSent) {
      state = "working";
    } else if (draft) {
      state = "needs_input";
      reason = "approve_draft";
    } else {
      state = "working"; // the agent has not reached this one yet
    }

    const question = (core.blocking_question as string | undefined) || null;

    return {
      key,
      quote,
      thread,
      reference,
      supplier: supplierLabel(quote),
      state,
      reason,
      missing,
      question,
      draft,
      followUp: state === "working" && lastSent ? followUpClock(lastSent, now) : null,
      quotedAt: String(quote.updated_at ?? thread.updated_at ?? ""),
    };
  });
}

// ── Parts ────────────────────────────────────────────────────────────────────
// A buyer arrives with a part number. A part's rows are one per supplier and
// service tier — Quick Turn and Standard are different offers and must never be
// compared as one — with the quantity breaks laid out as columns.

export type PriceCell = { text: string; value: number | null; lead: string | null; leadDays: number | null };

export type PartRow = {
  entry: QuoteEntry;
  tier: string | null;
  prices: Map<string, PriceCell>;
  leadDays: number | null;
  leadText: string | null;
  moq: string | null;
  nre: string | null;
  validUntil: string | null;
};

export type Part = {
  partNumber: string;
  manufacturer: string | null;
  rows: PartRow[];
  /** Quantity columns, ascending. "" is a price quoted with no quantity. */
  quantities: string[];
  bestPrice: { value: number; text: string; qty: string } | null;
  bestLeadDays: number | null;
  lastQuoted: string;
};

const scalar = (core: QuoteCore, ...keys: string[]): string | null => {
  for (const k of keys) {
    const v = core[k];
    if (v != null && v !== "" && typeof v !== "object") return String(v);
  }
  return null;
};

export function buildParts(entries: QuoteEntry[]): Part[] {
  const parts = new Map<string, Part>();

  for (const entry of entries) {
    const core = coreOf(entry.quote.extracted);
    const reqs = requirementsOf(entry.thread);
    const breaks = priceRows(core);
    const fallbackPart = reqs.our_part_number || reqs.mfg_part_number || entry.reference;

    // A supplier with no priced lines still belongs on the part, as an empty row:
    // "asked, not yet priced" is information.
    const lines = breaks.length ? breaks : [{ part_number: fallbackPart } as PriceBreak];

    const byRow = new Map<string, { part: string; tier: string | null; lines: PriceBreak[] }>();
    for (const br of lines) {
      const part = String(br.part_number || fallbackPart);
      const tier = br.service_tier ? String(br.service_tier) : null;
      const k = `${part}|${tier ?? ""}`;
      if (!byRow.has(k)) byRow.set(k, { part, tier, lines: [] });
      byRow.get(k)!.lines.push(br);
    }

    for (const { part: partNumber, tier, lines: rowLines } of byRow.values()) {
      let part = parts.get(partNumber);
      if (!part) {
        part = {
          partNumber,
          manufacturer: (core.manufacturer as string) || reqs.manufacturer || null,
          rows: [],
          quantities: [],
          bestPrice: null,
          bestLeadDays: null,
          lastQuoted: "",
        };
        parts.set(partNumber, part);
      }

      const prices = new Map<string, PriceCell>();
      const leads: number[] = [];
      const leadTexts = new Set<string>();
      for (const br of rowLines) {
        if (br.unit_price == null) continue;
        const qty = br.quantity == null ? "" : String(br.quantity);
        const leadDays = leadTimeToDays(br.lead_time);
        if (leadDays != null) leads.push(leadDays);
        if (br.lead_time) leadTexts.add(String(br.lead_time));
        prices.set(qty, {
          text: String(br.unit_price),
          value: priceToNumber(br.unit_price),
          lead: br.lead_time ? String(br.lead_time) : null,
          leadDays,
        });
      }

      part.rows.push({
        entry,
        tier,
        prices,
        leadDays: leads.length ? Math.min(...leads) : null,
        leadText: leadTexts.size === 1 ? [...leadTexts][0] : null,
        moq: scalar(core, "moq"),
        nre: scalar(core, "nre"),
        validUntil: scalar(core, "quote_valid_until", "validity"),
      });
    }
  }

  for (const part of parts.values()) {
    const qtys = new Set<string>();
    for (const row of part.rows) for (const q of row.prices.keys()) qtys.add(q);
    part.quantities = [...qtys].sort((a, b) => Number(a || 0) - Number(b || 0));

    for (const row of part.rows) {
      for (const [qty, cell] of row.prices) {
        if (cell.value != null && (!part.bestPrice || cell.value < part.bestPrice.value)) {
          part.bestPrice = { value: cell.value, text: cell.text, qty };
        }
      }
      if (row.leadDays != null && (part.bestLeadDays == null || row.leadDays < part.bestLeadDays)) {
        part.bestLeadDays = row.leadDays;
      }
      if (row.entry.quotedAt > part.lastQuoted) part.lastQuoted = row.entry.quotedAt;
    }
    part.rows.sort((a, b) => a.entry.supplier.localeCompare(b.entry.supplier));
  }

  return [...parts.values()].sort((a, b) => b.lastQuoted.localeCompare(a.lastQuoted));
}

/** Parts an entry's lines were quoted on — used to link a list row to its part. */
export function partsOfEntry(parts: Part[], entry: QuoteEntry): string[] {
  return parts.filter((p) => p.rows.some((r) => r.entry.key === entry.key)).map((p) => p.partNumber);
}

/** Messages and runs behind a part, for its "Source emails" section. */
export function sourcesOf(part: Part): { messages: Message[]; runs: Run[] } {
  const threads = new Map(part.rows.map((r) => [r.entry.thread.id, r.entry.thread]));
  const messages = [...threads.values()]
    .flatMap((t) => t.messages ?? [])
    .sort((a, b) => String(a.sent_at ?? "").localeCompare(String(b.sent_at ?? "")));
  const runs = [...threads.values()]
    .flatMap((t) => t.runs ?? [])
    .sort((a, b) => String(b.processed_at ?? "").localeCompare(String(a.processed_at ?? "")));
  return { messages, runs };
}

export const fieldLabel = (key: string): string =>
  key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const when = (v: string | null | undefined): string =>
  String(v ?? "").replace("T", " ").slice(0, 16);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const shortDate = (v: string | Date | null | undefined): string => {
  if (!v) return "—";
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : `${MONTHS[d.getMonth()]} ${d.getDate()}`;
};
