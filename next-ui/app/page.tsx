"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

type Interaction = {
  message_id: string;
  subject: string;
  sender: string;
  sent_at: string;
  classification: string | null;
  draft_reply: string | null;
  error: string | null;
  processed_at: string | null;
  reply_sent_at: string | null;
  result: ProcessingResult | null;
  collection_form: CollectionForm | null;
};

type ActionState = {
  label: string;
  detail?: string;
};

type ProcessingResult = {
  classification: string;
  rfq_requirements: {
    quantities_requested: number[];
    required_fields: string[];
  } | null;
  supplier_quote: SupplierQuote | null;
};

type SupplierQuote = {
  rfq_reference: string | null;
  supplier_name: string | null;
  quote_id: string | null;
  quote_valid_until: string | null;
  incoterms: string | null;
  price_breaks: PriceBreak[];
  long_lead_time_parts: string[];
  coo: string | null;
  payment_terms: string | null;
  moq: string | null;
  nre: string | null;
  blocking_question: string | null;
  missing_fields: {
    per_part: { part_number: string; missing: string[] }[];
    quote_level: string[];
  };
};

type PriceBreak = {
  part_number: string;
  quantity: number;
  unit_price: string;
  lead_time: string | null;
};

type CollectionForm = {
  type: string;
  status: string;
  fields?: {
    key: string;
    label: string;
    value: string | number | PriceBreak[] | null;
    required?: boolean;
    status: string;
  }[];
  fields_to_collect?: {
    key: string;
    required: boolean;
    value: string | null;
    status: string;
  }[];
  quantities_requested?: number[];
  price_breaks?: PriceBreak[];
  missing_items?: string[];
  flags?: {
    blocking_question: string | null;
    long_lead_time_parts: string[];
  };
};

const API_BASE = process.env.NEXT_PUBLIC_FORGEFLOW_API_BASE || "http://127.0.0.1:8000";

export default function DashboardPage() {
  const [rows, setRows] = useState<Interaction[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<ActionState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stats = useMemo(() => {
    return {
      total: rows.length,
      pending: rows.filter((row) => !row.classification && !row.error).length,
      drafts: rows.filter((row) => row.draft_reply && !row.reply_sent_at).length,
      sent: rows.filter((row) => row.reply_sent_at).length,
      quotes: rows.filter((row) => row.result?.supplier_quote).length
    };
  }, [rows]);

  async function api<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed: ${response.status}`);
    }
    return payload as T;
  }

  async function refresh() {
    const data = await api<Interaction[]>("/api/interactions");
    setRows(data);
  }

  async function runAction(label: string, fn: () => Promise<void>) {
    setError(null);
    setAction({ label });
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAction(null);
      setLoading(false);
    }
  }

  useEffect(() => {
    runAction("Loading interactions", async () => refresh());
  }, []);

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>ForgeFlow</h1>
          <p>Outlook agent processing dashboard</p>
        </div>
        <div className="actions">
          <button disabled={Boolean(action)} onClick={() => runAction("Syncing Outlook", async () => {
            const result = await api<{ ingested: number }>("/api/sync-outlook", { method: "POST" });
            setAction({ label: "Syncing Outlook", detail: `${result.ingested} new emails` });
          })}>
            Sync Outlook
          </button>
          <button disabled={Boolean(action)} onClick={() => runAction("Processing emails", async () => {
            const result = await api<{ processed: number }>("/api/process", { method: "POST" });
            setAction({ label: "Processing emails", detail: `${result.processed} processed` });
          })}>
            Process
          </button>
        </div>
      </header>

      {(action || loading) && (
        <section className="progressPanel" aria-live="polite">
          <div className="progressCopy">
            <strong>{action?.label || "Loading"}</strong>
            <span>{action?.detail || "Waiting for the backend to finish..."}</span>
          </div>
          <div className="progressTrack">
            <div className="progressBar" />
          </div>
        </section>
      )}

      {error && <section className="errorPanel">{error}</section>}

      <section className="stats">
        <div><span>{stats.total}</span>Total</div>
        <div><span>{stats.quotes}</span>Quotes</div>
        <div><span>{stats.pending}</span>Pending</div>
        <div><span>{stats.drafts}</span>Drafts</div>
      </section>

      <section className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>From</th>
              <th>Subject</th>
              <th>Class</th>
              <th>Decision Data</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const quote = row.result?.supplier_quote || null;
              const isExpanded = expandedId === row.message_id;
              return (
                <Fragment key={row.message_id}>
                  <tr>
                    <td>{formatDate(row.sent_at)}</td>
                    <td>{row.sender}</td>
                    <td>
                      <button
                        className="linkButton"
                        onClick={() => setExpandedId(isExpanded ? null : row.message_id)}
                      >
                        {row.subject}
                      </button>
                    </td>
                    <td><span className="pill">{row.classification || "pending"}</span></td>
                    <td>
                      {row.collection_form ? (
                        <FormSummary form={row.collection_form} quote={quote} />
                      ) : (
                        <span className="muted">No quote fields</span>
                      )}
                    </td>
                    <td>
                      {row.error && <pre className="rowError">{row.error}</pre>}
                      <button className="secondaryButton" onClick={() => setExpandedId(isExpanded ? null : row.message_id)}>
                        {isExpanded ? "Hide Details" : "View Details"}
                      </button>
                      {!row.error && row.draft_reply && (
                        <>
                          {row.reply_sent_at ? (
                            <div className="sent">Reply sent {formatDate(row.reply_sent_at)}</div>
                          ) : (
                            <button
                              disabled={Boolean(action)}
                              onClick={() => runAction("Sending reply", async () => {
                                await api("/api/send-reply", {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ message_id: row.message_id })
                                });
                              })}
                            >
                              Send Reply
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={6} className="detailsCell">
                        <InteractionDetails row={row} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </section>
    </main>
  );
}

function QuoteSummary({ quote }: { quote: SupplierQuote }) {
  const missingCount = quote.missing_fields.quote_level.length + quote.missing_fields.per_part.length;
  return (
    <div className="quoteSummary">
      <span>{quote.supplier_name || "Unknown supplier"}</span>
      <span>{quote.price_breaks.length} price row{quote.price_breaks.length === 1 ? "" : "s"}</span>
      <span>{missingCount ? `${missingCount} missing` : "complete"}</span>
      {quote.long_lead_time_parts.length > 0 && <span>long lead</span>}
    </div>
  );
}

function FormSummary({ form, quote }: { form: CollectionForm; quote: SupplierQuote | null }) {
  if (form.type === "rfq_requirements") {
    return (
      <div className="quoteSummary">
        <span>RFQ form</span>
        <span>{form.fields_to_collect?.length || 0} fields</span>
        <span>{form.quantities_requested?.join(", ") || "no quantities"}</span>
      </div>
    );
  }
  if (quote) {
    return <QuoteSummary quote={quote} />;
  }
  return <span className="muted">{form.status}</span>;
}

function InteractionDetails({ row }: { row: Interaction }) {
  const quote = row.result?.supplier_quote;
  const form = row.collection_form;
  if (form?.type === "rfq_requirements") {
    return (
      <div className="detailsPanel">
        <div className="detailsHeader">
          <div>
            <h2>{row.subject}</h2>
            <p>{row.sender}</p>
          </div>
          <span className="statusNeedsWork">Collection form created</span>
        </div>
        <section className="detailColumns">
          <div>
            <h3>Quantities Requested</h3>
            <p>{form.quantities_requested?.join(", ") || "No quantities extracted"}</p>
          </div>
          <div>
            <h3>Fields To Collect</h3>
            <ul>
              {(form.fields_to_collect || []).map((field) => (
                <li key={field.key}>{field.key}</li>
              ))}
            </ul>
          </div>
        </section>
        <JsonForm form={form} />
      </div>
    );
  }
  if (!quote) {
    return (
      <div className="detailsPanel">
        <h2>{row.subject}</h2>
        <p>No quote fields were extracted for this email.</p>
      </div>
    );
  }

  return (
    <div className="detailsPanel">
      <div className="detailsHeader">
        <div>
          <h2>{row.subject}</h2>
          <p>{row.sender}</p>
        </div>
        <span className={isComplete(quote) ? "statusGood" : "statusNeedsWork"}>
          {isComplete(quote) ? "Ready for review" : "Needs follow-up"}
        </span>
      </div>

      <section className="fieldGrid">
        {(form?.fields || []).map((field) => (
          <Field
            key={field.key}
            label={`${field.label}${field.required ? " *" : ""}`}
            value={displayFieldValue(field.value)}
            status={field.status}
          />
        ))}
      </section>

      <section className="detailSection">
        <h3>Price Breaks</h3>
        {quote.price_breaks.length ? (
          <table className="innerTable">
            <thead>
              <tr>
                <th>Part</th>
                <th>Quantity</th>
                <th>Unit Price</th>
                <th>Lead Time</th>
              </tr>
            </thead>
            <tbody>
              {quote.price_breaks.map((priceBreak, index) => (
                <tr key={`${priceBreak.part_number}-${priceBreak.quantity}-${index}`}>
                  <td>{priceBreak.part_number}</td>
                  <td>{priceBreak.quantity}</td>
                  <td>{priceBreak.unit_price}</td>
                  <td>{priceBreak.lead_time || <span className="missing">Missing</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="missing">No price breaks extracted.</p>
        )}
      </section>

      <section className="detailColumns">
        <div>
          <h3>Missing Items</h3>
          {missingItems(quote).length ? (
            <ul>
              {missingItems(quote).map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : (
            <p className="statusGoodText">No missing required fields.</p>
          )}
        </div>
        <div>
          <h3>Flags</h3>
          {quote.blocking_question && <p>{quote.blocking_question}</p>}
          {quote.long_lead_time_parts.length ? (
            <ul>{quote.long_lead_time_parts.map((part) => <li key={part}>{part}</li>)}</ul>
          ) : (
            <p className="muted">No long-lead parts flagged.</p>
          )}
        </div>
      </section>

      {row.draft_reply && (
        <section className="detailSection">
          <h3>Generated Reply</h3>
          <pre>{row.draft_reply}</pre>
          {row.reply_sent_at && <div className="sent">Sent {formatDate(row.reply_sent_at)}</div>}
        </section>
      )}

      {form && <JsonForm form={form} />}
    </div>
  );
}

function JsonForm({ form }: { form: CollectionForm }) {
  return (
    <section className="detailSection">
      <h3>Agent Collection Form JSON</h3>
      <pre className="jsonBlock">{JSON.stringify(form, null, 2)}</pre>
    </section>
  );
}

function Field({
  label,
  value,
  status
}: {
  label: string;
  value: string | null;
  status?: string;
}) {
  return (
    <div className={value ? "field" : "field fieldMissing"}>
      <span>{label}</span>
      <strong>{value || "Missing"}</strong>
      {status && <em>{status}</em>}
    </div>
  );
}

function displayFieldValue(value: string | number | PriceBreak[] | null | undefined) {
  if (value === null || value === undefined) return null;
  if (Array.isArray(value)) {
    return value.length ? `${value.length} price row${value.length === 1 ? "" : "s"}` : null;
  }
  return String(value);
}

function isComplete(quote: SupplierQuote) {
  return missingItems(quote).length === 0 && !quote.blocking_question;
}

function missingItems(quote: SupplierQuote) {
  const items = quote.missing_fields.quote_level.map((field) => field);
  for (const part of quote.missing_fields.per_part) {
    items.push(`${part.part_number}: ${part.missing.join(", ")}`);
  }
  return items;
}

function formatDate(value: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
