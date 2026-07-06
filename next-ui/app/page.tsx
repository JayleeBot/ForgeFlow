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
    requested_tiers?: string[];
    our_part_number?: string | null;
    manufacturer?: string | null;
    mfg_part_number?: string | null;
  } | null;
  supplier_quote: SupplierQuote | null;
};

type SupplierQuote = {
  rfq_reference: string | null;
  supplier_name: string | null;
  quote_id: string | null;
  quote_valid_until: string | null;
  incoterms: string | null;
  manufacturer?: string | null;
  mfg_part_number?: string | null;
  price_breaks: PriceBreak[];
  long_lead_time_parts: string[];
  coo: string | null;
  payment_terms: string | null;
  moq: string | null;
  nre: string | null;
  blocking_question: string | null;
  missing_fields: {
    per_part: { part_number: string; missing: string[]; service_tier?: string | null }[];
    quote_level: string[];
  };
};

type PriceBreak = {
  part_number: string;
  quantity: number;
  unit_price: string;
  lead_time: string | null;
  service_tier?: string | null;
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
  requested_tiers?: string[];
  our_part_number?: string | null;
  manufacturer?: string | null;
  mfg_part_number?: string | null;
  expected_mfg_part_number?: string | null;
  price_breaks?: PriceBreak[];
  missing_items?: string[];
  flags?: {
    blocking_question: string | null;
    long_lead_time_parts: string[];
    mfg_mismatch?: { expected: string; quoted: string } | null;
  };
};

type Scenario = {
  id: string;
  label: string;
  files: string[];
};

type SimulatorStep = {
  file: string;
  subject: string;
  agent: string;
  classification: string;
  result: ProcessingResult;
  draft_reply: string | null;
};

type SimulatorRun = {
  scenario: string;
  steps: SimulatorStep[];
};

const API_BASE = process.env.NEXT_PUBLIC_FORGEFLOW_API_BASE || "http://127.0.0.1:8000";

export default function DashboardPage() {
  const [rows, setRows] = useState<Interaction[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenario, setSelectedScenario] = useState("");
  const [manualEmails, setManualEmails] = useState<string[]>([defaultEmail(1)]);
  const [activeTab, setActiveTab] = useState<"dashboard" | "playground">("dashboard");
  const [simulatorRun, setSimulatorRun] = useState<SimulatorRun | null>(null);
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
    const [data, scenarioData] = await Promise.all([
      api<Interaction[]>("/api/interactions"),
      api<Scenario[]>("/api/simulator/scenarios")
    ]);
    setRows(data);
    setScenarios(scenarioData);
    setSelectedScenario((current) => current || scenarioData[0]?.id || "");
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

      <nav className="tabs" aria-label="Dashboard sections">
        <button
          className={activeTab === "dashboard" ? "activeTab" : ""}
          onClick={() => setActiveTab("dashboard")}
        >
          RFQ Dashboard
        </button>
        <button
          className={activeTab === "playground" ? "activeTab" : ""}
          onClick={() => setActiveTab("playground")}
        >
          Playground
        </button>
      </nav>

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

      {activeTab === "playground" ? (
        <PlaygroundTab
          action={action}
          api={api}
          manualEmails={manualEmails}
          runAction={runAction}
          scenarios={scenarios}
          selectedScenario={selectedScenario}
          setManualEmails={setManualEmails}
          setSelectedScenario={setSelectedScenario}
          setSimulatorRun={setSimulatorRun}
          simulatorRun={simulatorRun}
        />
      ) : (
        <DashboardTab
          action={action}
          expandedId={expandedId}
          rows={rows}
          runAction={runAction}
          setExpandedId={setExpandedId}
          stats={stats}
          api={api}
        />
      )}
    </main>
  );
}

function PlaygroundTab({
  action,
  api,
  manualEmails,
  runAction,
  scenarios,
  selectedScenario,
  setManualEmails,
  setSelectedScenario,
  setSimulatorRun,
  simulatorRun
}: {
  action: ActionState | null;
  api: <T>(path: string, options?: RequestInit) => Promise<T>;
  manualEmails: string[];
  runAction: (label: string, fn: () => Promise<void>) => Promise<void>;
  scenarios: Scenario[];
  selectedScenario: string;
  setManualEmails: (emails: string[]) => void;
  setSelectedScenario: (scenario: string) => void;
  setSimulatorRun: (run: SimulatorRun) => void;
  simulatorRun: SimulatorRun | null;
}) {
  function addEmail() {
    setManualEmails([...manualEmails, defaultEmail(manualEmails.length + 1)]);
  }

  function removeEmail(index: number) {
    setManualEmails(manualEmails.filter((_, itemIndex) => itemIndex !== index));
  }

  function updateEmail(index: number, value: string) {
    const next = [...manualEmails];
    next[index] = value;
    setManualEmails(next);
  }

  function newThread() {
    setManualEmails([defaultEmail(1)]);
    setSimulatorRun({
      scenario: "manual_playground",
      steps: []
    });
  }

  return (
    <section className="simulatorPanel">
      <div>
        <h2>Local Email Simulator</h2>
        <p>Inject sample RFQ threads or write your own emails, then inspect which agent responded.</p>
      </div>
      <div className="simulatorControls">
        <select value={selectedScenario} onChange={(event) => setSelectedScenario(event.target.value)}>
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>{scenario.label}</option>
          ))}
        </select>
        <button disabled={Boolean(action) || !selectedScenario} onClick={() => runAction("Running simulator", async () => {
          const result = await api<SimulatorRun>("/api/simulator/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ scenario_id: selectedScenario })
          });
          setSimulatorRun(result);
        })}>
          Run Scenario
        </button>
      </div>
      {selectedScenario && (
        <div className="scenarioFiles">
          {(scenarios.find((scenario) => scenario.id === selectedScenario)?.files || []).map((file) => (
            <span key={file}>{file}</span>
          ))}
        </div>
      )}
      <div className="manualPlayground">
        <div className="manualHeader">
          <div>
            <h3>Manual Thread Playground</h3>
            <p>Build a thread message by message. Add the buyer RFQ, run it, add a supplier reply, run again, and keep going.</p>
          </div>
          <div className="manualActions">
            <button disabled={Boolean(action)} onClick={newThread}>New Thread</button>
            <button disabled={Boolean(action)} onClick={addEmail}>Add Reply</button>
            <button disabled={Boolean(action)} onClick={() => runAction("Running manual thread", async () => {
              const result = await api<SimulatorRun>("/api/simulator/manual", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ emails: manualEmails })
              });
              setSimulatorRun(result);
            })}>
              Run Current Thread
            </button>
          </div>
        </div>
        <div className="playgroundWorkspace">
          <div className="threadTimeline">
            {manualEmails.map((email, index) => (
              <article key={index} className="threadMessage">
                <header>
                  <strong>{index === 0 ? "Buyer RFQ" : `Reply ${index}`}</strong>
                  <button disabled={manualEmails.length === 1 || Boolean(action)} onClick={() => removeEmail(index)}>
                    Remove
                  </button>
                </header>
                <textarea value={email} onChange={(event) => updateEmail(index, event.target.value)} />
              </article>
            ))}
          </div>
          <div className="playgroundResults">
            <h3>Agent Trace</h3>
            {simulatorRun ? <AgentTrace run={simulatorRun} /> : <p className="muted">Run the current thread to see agent responses and extracted fields.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}

function AgentTrace({ run }: { run: SimulatorRun }) {
  return (
    <div className="agentTrace">
      {run.steps.map((step, index) => (
        <div key={`${step.file}-${index}`}>
          <strong>{index + 1}. {step.agent}</strong>
          <span>{step.classification}</span>
          <p>{step.subject}</p>
          <small>{step.file}</small>
          <SimulatorStepDetails step={step} />
          {step.draft_reply && <pre>{step.draft_reply}</pre>}
        </div>
      ))}
    </div>
  );
}

function SimulatorStepDetails({ step }: { step: SimulatorStep }) {
  if (step.result.supplier_quote) {
    const quote = step.result.supplier_quote;
    return (
      <div className="traceDetails">
        {step.result.rfq_requirements && (
          <section className="detailSection">
            <h4>RFQ Collection Schema Used</h4>
            <div className="traceGrid">
              <Field label="Our Part Number" value={step.result.rfq_requirements.our_part_number || "None"} />
              <Field label="Manufacturer" value={step.result.rfq_requirements.manufacturer || "None"} />
              <Field label="Mfg Part Number" value={step.result.rfq_requirements.mfg_part_number || "None"} />
              <Field label="Quantities" value={step.result.rfq_requirements.quantities_requested.join(", ") || "None"} />
              <Field label="Required Fields" value={step.result.rfq_requirements.required_fields.join(", ")} />
              <Field label="Requested Tiers" value={step.result.rfq_requirements.requested_tiers?.join(", ") || "None"} />
            </div>
          </section>
        )}
        {mfgMismatch(quote, step.result.rfq_requirements) && (
          <p className="missing">
            ⚠ Mfg part number mismatch — RFQ specified{" "}
            <strong>{step.result.rfq_requirements?.mfg_part_number}</strong>, supplier quoted{" "}
            <strong>{quote.mfg_part_number}</strong>. Buyer must confirm the substitute.
          </p>
        )}
        <h4>Supplier Extraction</h4>
        <section className="fieldGrid">
          <Field label="Supplier" value={quote.supplier_name} />
          <Field label="RFQ Ref" value={quote.rfq_reference} />
          <Field label="Manufacturer" value={quote.manufacturer ?? null} />
          <Field label="Mfg Part Number" value={quote.mfg_part_number ?? null} />
          <Field label="Payment Terms" value={quote.payment_terms} />
          <Field label="MOQ" value={quote.moq} />
          <Field label="NRE" value={quote.nre} />
          <Field label="COO" value={quote.coo} />
        </section>
        <section className="detailSection">
          <h4>Price Breaks</h4>
          <PriceBreakTable priceBreaks={quote.price_breaks} />
        </section>
        <section className="detailColumns">
          <div>
            <h4>Missing Items</h4>
            {missingItems(quote, step.result.rfq_requirements).length ? (
              <ul>{missingItems(quote, step.result.rfq_requirements).map((item) => <li key={item}>{item}</li>)}</ul>
            ) : (
              <p className="statusGoodText">No missing fields.</p>
            )}
          </div>
          <div>
            <h4>Flags</h4>
            {quote.blocking_question && <p>{quote.blocking_question}</p>}
            {quote.long_lead_time_parts.length ? (
              <ul>{quote.long_lead_time_parts.map((item) => <li key={item}>{item}</li>)}</ul>
            ) : (
              <p className="muted">No flags.</p>
            )}
          </div>
        </section>
      </div>
    );
  }

  if (step.result.rfq_requirements) {
    return (
      <div className="traceDetails">
        <h4>RFQ Collection Schema</h4>
        <div className="traceGrid">
          <Field label="Our Part Number" value={step.result.rfq_requirements.our_part_number || "None"} />
          <Field label="Manufacturer" value={step.result.rfq_requirements.manufacturer || "None"} />
          <Field label="Mfg Part Number" value={step.result.rfq_requirements.mfg_part_number || "None"} />
          <Field label="Quantities" value={step.result.rfq_requirements.quantities_requested.join(", ") || "None"} />
          <Field label="Required Fields" value={step.result.rfq_requirements.required_fields.join(", ")} />
          <Field label="Requested Tiers" value={step.result.rfq_requirements.requested_tiers?.join(", ") || "None"} />
        </div>
        <pre className="jsonBlock">{JSON.stringify(step.result.rfq_requirements, null, 2)}</pre>
      </div>
    );
  }

  return <p className="muted">No structured payload for this step.</p>;
}

function DashboardTab({
  action,
  api,
  expandedId,
  rows,
  runAction,
  setExpandedId,
  stats
}: {
  action: ActionState | null;
  api: <T>(path: string, options?: RequestInit) => Promise<T>;
  expandedId: string | null;
  rows: Interaction[];
  runAction: (label: string, fn: () => Promise<void>) => Promise<void>;
  setExpandedId: (id: string | null) => void;
  stats: { total: number; quotes: number; pending: number; drafts: number };
}) {
  return (
    <>
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
                      <button className="linkButton" onClick={() => setExpandedId(isExpanded ? null : row.message_id)}>
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
    </>
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
            {form.mfg_part_number && (
              <>
                <h3>Manufacturer / Mfg Part Number</h3>
                <p>{[form.manufacturer, form.mfg_part_number].filter(Boolean).join(" / ")}</p>
              </>
            )}
            {form.requested_tiers && form.requested_tiers.length > 0 && (
              <>
                <h3>Requested Tiers</h3>
                <p>{form.requested_tiers.join(", ")}</p>
              </>
            )}
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

  const mismatch = form?.flags?.mfg_mismatch;
  const ready = isComplete(quote) && !mismatch;
  return (
    <div className="detailsPanel">
      <div className="detailsHeader">
        <div>
          <h2>{row.subject}</h2>
          <p>{row.sender}</p>
        </div>
        <span className={ready ? "statusGood" : "statusNeedsWork"}>
          {ready ? "Ready for review" : "Needs follow-up"}
        </span>
      </div>

      {mismatch && (
        <p className="missing">
          ⚠ Mfg part number mismatch — RFQ specified <strong>{mismatch.expected}</strong>, supplier
          quoted <strong>{mismatch.quoted}</strong>. Buyer must confirm the substitute.
        </p>
      )}

      <section className="fieldGrid">
        {(quote.manufacturer || quote.mfg_part_number) && (
          <Field label="Mfg Part Number" value={[quote.manufacturer, quote.mfg_part_number].filter(Boolean).join(" / ")} />
        )}
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
        <PriceBreakTable priceBreaks={quote.price_breaks} />
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

function PriceBreakTable({ priceBreaks }: { priceBreaks: PriceBreak[] }) {
  if (!priceBreaks.length) {
    return <p className="missing">No price breaks extracted.</p>;
  }
  const hasTiers = priceBreaks.some((priceBreak) => priceBreak.service_tier);
  return (
    <table className="innerTable">
      <thead>
        <tr>
          {hasTiers && <th>Tier</th>}
          <th>Part</th>
          <th>Quantity</th>
          <th>Unit Price</th>
          <th>Lead Time</th>
        </tr>
      </thead>
      <tbody>
        {priceBreaks.map((priceBreak, index) => (
          <tr key={`${priceBreak.service_tier ?? ""}-${priceBreak.part_number}-${priceBreak.quantity}-${index}`}>
            {hasTiers && <td>{priceBreak.service_tier || "—"}</td>}
            <td>{priceBreak.part_number}</td>
            <td>{priceBreak.quantity}</td>
            <td>{priceBreak.unit_price}</td>
            <td>{priceBreak.lead_time || <span className="missing">Missing</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function isComplete(quote: SupplierQuote) {
  return missingItems(quote).length === 0 && !quote.blocking_question;
}

function partLabel(part: { part_number: string; service_tier?: string | null }) {
  return part.service_tier ? `${part.part_number} (${part.service_tier})` : part.part_number;
}

function normTier(tier: string | null | undefined) {
  return (tier || "").trim().toLowerCase();
}

// Presence-driven: the buyer named an MFG part number and the supplier quoted a different one.
function mfgMismatch(quote: SupplierQuote, requirements?: ProcessingResult["rfq_requirements"]) {
  const expected = requirements?.mfg_part_number;
  const quoted = quote.mfg_part_number;
  return Boolean(expected && quoted && normTier(expected) !== normTier(quoted));
}

function missingItems(quote: SupplierQuote, requirements?: ProcessingResult["rfq_requirements"]) {
  const required = requirements?.required_fields || [];
  const tiers = requirements?.requested_tiers || [];
  const items: string[] = [];
  if (required.includes("price_breaks")) {
    if (tiers.length) {
      for (const tier of tiers) {
        if (!quote.price_breaks.some((row) => normTier(row.service_tier) === normTier(tier))) {
          items.push(`${tier}: price_breaks`);
        }
      }
    } else if (quote.price_breaks.length === 0) {
      items.push("price_breaks");
    }
  }
  if (required.includes("lead_time")) {
    for (const part of quote.missing_fields.per_part) {
      if (part.missing.includes("lead_time")) {
        items.push(`${partLabel(part)}: lead_time`);
      }
    }
    if (tiers.length) {
      for (const tier of tiers) {
        const rows = quote.price_breaks.filter((row) => normTier(row.service_tier) === normTier(tier));
        if (rows.length > 0 && !rows.some((row) => row.lead_time)) {
          items.push(`${tier}: lead_time`);
        }
      }
    } else if (quote.price_breaks.length > 0 && !quote.price_breaks.some((row) => row.lead_time)) {
      items.push("lead_time");
    }
  }
  for (const field of ["coo", "payment_terms", "moq", "nre"] as const) {
    if (required.includes(field) && !quote[field]) {
      items.push(field);
    }
  }
  for (const field of quote.missing_fields.quote_level) {
    if (!items.includes(field)) {
      items.push(field);
    }
  }
  for (const part of quote.missing_fields.per_part) {
    const item = `${partLabel(part)}: ${part.missing.join(", ")}`;
    if (!items.includes(item) && (!requirements || part.missing.some((field) => field !== "lead_time"))) {
      items.push(item);
    }
  }
  // MFG part number is presence-driven: required only when the buyer named one.
  if (requirements?.mfg_part_number && !quote.mfg_part_number) {
    items.push("mfg_part_number");
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

function defaultEmail(index: number) {
  const date = `Wed, 20 May 2026 10:0${index}:00 -0400`;
  if (index === 1) {
    return [
      "From: Buyer <buyer@example.com>",
      "To: Supplier <supplier@example.com>",
      "Cc: forgeflow.demo@outlook.com",
      "Subject: RFQ - Demo Part #ABC-100",
      `Date: ${date}`,
      `Message-ID: <manual-demo-${index}@forgeflow>`,
      "",
      "Hi,",
      "",
      "Please quote ABC-100 at 100, 250, and 500 pcs.",
      "Please include unit price, lead time, MOQ, payment terms, COO, and NRE if applicable.",
      "",
      "Thanks"
    ].join("\n");
  }
  if (index === 2) {
    return [
      "From: Supplier <supplier@example.com>",
      "To: Buyer <buyer@example.com>",
      "Cc: forgeflow.demo@outlook.com",
      "Subject: Re: RFQ - Demo Part #ABC-100",
      `Date: ${date}`,
      `Message-ID: <manual-demo-${index}@forgeflow>`,
      "",
      "Hi,",
      "",
      "For ABC-100, unit price is $2.40 at 100 pcs, $2.10 at 250 pcs, and $1.90 at 500 pcs.",
      "Lead time is 6 weeks. MOQ is 100 pcs. COO is Mexico.",
      "",
      "Best"
    ].join("\n");
  }
  return [
    "From: Supplier <supplier@example.com>",
    "To: Buyer <buyer@example.com>",
    "Cc: forgeflow.demo@outlook.com",
    "Subject: Re: RFQ - Demo Part #ABC-100",
    `Date: ${date}`,
    `Message-ID: <manual-demo-${index}@forgeflow>`,
    "",
    "Payment terms are Net 30. No NRE required."
  ].join("\n");
}
