// The shape the deploy-time snapshot ships, which is also what functions/rfqs.ts
// returns. Nearly everything is optional: these rows are whatever the agent
// managed to extract from a supplier's prose, not a validated form.

export type PriceBreak = {
  part_number?: string | null;
  service_tier?: string | null;
  quantity?: number | string | null;
  unit_price?: number | string | null;
  lead_time?: string | null;
};

/**
 * A missing field is either a bare name (quote_level) or, under per_part, an
 * object naming the part and tier it is missing on.
 */
export type MissingEntry =
  | string
  | { missing?: string; part_number?: string | null; service_tier?: string | null };

export type MissingFields = MissingEntry[] | Record<string, MissingEntry[]> | null;

/** A supplier's extracted quote: known keys, plus whatever scalars the agent found. */
export type QuoteCore = {
  supplier_name?: string | null;
  rfq_reference?: string | null;
  price_breaks?: PriceBreak[] | Record<string, Record<string, unknown>> | null;
  missing_fields?: MissingFields;
  [key: string]: unknown;
};

export type RfqRequirements = {
  our_part_number?: string | null;
  manufacturer?: string | null;
  mfg_part_number?: string | null;
  quantities_requested?: number[];
  required_fields?: string[];
  [key: string]: unknown;
};

export type Extracted = {
  supplier_quote?: QuoteCore | null;
  rfq_requirements?: RfqRequirements | null;
  [key: string]: unknown;
};

export type SupplierQuote = {
  id: string;
  rfq_id: string;
  supplier_name?: string | null;
  supplier_email?: string | null;
  status?: string | null;
  extracted?: Extracted | QuoteCore | null;
  missing_fields?: MissingFields;
  latest_message_id?: string | null;
  updated_at?: string | null;
};

export type Message = {
  message_id: string;
  thread_id: string;
  subject?: string | null;
  sender?: string | null;
  recipients?: string | null;
  sent_at?: string | null;
  body_text?: string | null;
  draft_reply?: string | null;
};

export type Run = {
  message_id: string;
  thread_id?: string | null;
  session_id?: string | null;
  sent_reply?: boolean | null;
  processed_at?: string | null;
};

export type Rfq = {
  id: string;
  thread_id: string;
  subject?: string | null;
  buyer_email?: string | null;
  /** The email classification, NOT a buyer-facing state. See rfqState() in data.ts. */
  status?: string | null;
  collection_form?: RfqRequirements | null;
  updated_at?: string | null;
  supplier_quotes?: SupplierQuote[];
  messages?: Message[];
  runs?: Run[];
};

export type Snapshot = {
  captured_at?: string | null;
  trigger_url?: string | null;
  rfqs?: Rfq[];
};
