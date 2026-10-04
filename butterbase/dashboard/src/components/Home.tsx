import { useState } from "react";
import { shortDate } from "../data";
import type { ClockStatus, Part, QuoteEntry, QuoteStateKey } from "../data";
import { ClockIcon } from "../charts/Clock";
import { seriesColor } from "../charts/palette";

export type Bucket = QuoteStateKey;

const ORDER: Bucket[] = ["ready", "needs_input", "working"];

const BUCKET: Record<Bucket, { title: string; color: string }> = {
  ready: { title: "Ready for review", color: seriesColor(0) },
  needs_input: { title: "Needs your input", color: seriesColor(1) },
  working: { title: "Agent working", color: seriesColor(2) },
};

const CLOCK_LABEL: Record<ClockStatus | "pending", string> = {
  overdue: "overdue",
  due_soon: "due soon",
  on_track: "on track",
  pending: "not chased yet",
};

function greeting(now: Date) {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/**
 * The share of quotes in each bucket, as one stacked bar. Segments are
 * separated by a surface gap rather than outlines, and each is clickable.
 */
function Pipeline({ counts, total, onOpen }: {
  counts: Record<Bucket, number>;
  total: number;
  onOpen: (b: Bucket) => void;
}) {
  const [hover, setHover] = useState<Bucket | null>(null);
  if (!total) return null;
  return (
    <div className="pipeline">
      <div className="pipeline-bar" onPointerLeave={() => setHover(null)}>
        {ORDER.filter((b) => counts[b]).map((b) => (
          <button
            key={b}
            className={`pipeline-seg${hover && hover !== b ? " dim" : ""}`}
            style={{ flexGrow: counts[b], background: BUCKET[b].color }}
            onPointerEnter={() => setHover(b)}
            onFocus={() => setHover(b)}
            onClick={() => onOpen(b)}
            aria-label={`${BUCKET[b].title}: ${counts[b]} of ${total}`}
          />
        ))}
      </div>
      <ul className="legend">
        {ORDER.map((b) => (
          <li key={b} className={hover === b ? "on" : undefined}>
            <span className="swatch" style={{ background: BUCKET[b].color }} />
            {BUCKET[b].title}
            <strong>{counts[b]}</strong>
            <span className="muted-inline">{Math.round((counts[b] / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Each part's suppliers split by state, one thin stacked bar per part, so the
 * buyer sees which parts are closest to a decision. Bars share one scale (the
 * part with the most suppliers fills the width), so length means supplier count.
 */
function PartProgress({ parts, onOpenPart }: { parts: Part[]; onOpenPart: (p: string) => void }) {
  const rows = parts.map((part) => {
    const seen = new Map<string, QuoteEntry>();
    for (const r of part.rows) seen.set(r.entry.key, r.entry);
    const quotes = [...seen.values()];
    const counts = { ready: 0, needs_input: 0, working: 0 } as Record<Bucket, number>;
    for (const q of quotes) counts[q.state] += 1;
    return { part, counts, total: quotes.length };
  });
  const widest = Math.max(1, ...rows.map((r) => r.total));
  rows.sort((a, b) => b.counts.ready / b.total - a.counts.ready / a.total);

  return (
    <ul className="part-progress">
      {rows.map(({ part, counts, total }) => (
        <li key={part.partNumber}>
          <button className="part-progress-row" onClick={() => onOpenPart(part.partNumber)}>
            <span className="pp-name">{part.partNumber}</span>
            <span className="pp-track">
              <span className="pp-bar" style={{ width: `${(total / widest) * 100}%` }}>
                {ORDER.filter((b) => counts[b]).map((b) => (
                  <span key={b} className="pp-seg" style={{ flexGrow: counts[b], background: BUCKET[b].color }}
                    title={`${BUCKET[b].title}: ${counts[b]}`} />
                ))}
              </span>
            </span>
            <span className="pp-count">
              {counts.ready}/{total} complete
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * The landing view answers one question: whose move is it. Each supplier quote
 * sits in exactly one bucket, so the three numbers add up to the total.
 */
export default function Home({
  entries,
  parts,
  buyer,
  onOpen,
  onOpenPart,
  partOf,
}: {
  entries: QuoteEntry[];
  parts: Part[];
  buyer: string | null;
  onOpen: (b: Bucket) => void;
  onOpenPart: (part: string) => void;
  partOf: (e: QuoteEntry) => string | null;
}) {
  const of = (s: Bucket) => entries.filter((e) => e.state === s);
  const ready = of("ready");
  const input = of("needs_input");
  const working = of("working");
  const counts = { ready: ready.length, needs_input: input.length, working: working.length };

  const questions = input.filter((e) => e.reason === "question").length;
  const drafts = input.filter((e) => e.reason === "approve_draft").length;

  const clocks: Record<ClockStatus | "pending", number> = { overdue: 0, due_soon: 0, on_track: 0, pending: 0 };
  for (const e of working) clocks[e.followUp?.status ?? "pending"] += 1;

  const suppliers = new Set(entries.map((e) => e.supplier.toLowerCase())).size;
  const rfqs = new Set(entries.map((e) => e.reference.toLowerCase())).size;

  // What deserves a look today, most pressing first: a supplier stalled on a
  // question, then the follow-up clock, then drafts waiting to go out.
  const rank = (e: QuoteEntry) =>
    e.reason === "question" ? 0
      : e.followUp?.status === "overdue" ? 1
      : e.followUp?.status === "due_soon" ? 2
      : e.reason === "approve_draft" ? 3
      : 9;
  const attention = entries.filter((e) => rank(e) < 9).sort((a, b) => rank(a) - rank(b)).slice(0, 5);

  const now = new Date();
  const partCount = parts.length;

  return (
    <>
      <section className="hello">
        <h2>
          {greeting(now)}
          {buyer ? `, ${buyer}` : ""}
        </h2>
        <p className="muted">
          {input.length
            ? `${input.length} quote${input.length === 1 ? " needs" : "s need"} you before the agent can move on.`
            : "Nothing is waiting on you."}{" "}
          {ready.length > 0 && `${ready.length} ${ready.length === 1 ? "is" : "are"} ready to compare.`}
        </p>
      </section>

      <div className="buckets">
        <button className="bucket" onClick={() => onOpen("ready")}>
          <span className="bucket-title">
            <span className="swatch" style={{ background: BUCKET.ready.color }} />
            Ready for review
          </span>
          <span className="bucket-n">{ready.length}</span>
          <span className="bucket-sub">Quotes complete — compare and decide</span>
          <span className="bucket-go">Compare suppliers →</span>
        </button>

        <button className="bucket" onClick={() => onOpen("needs_input")}>
          <span className="bucket-title">
            <span className="swatch" style={{ background: BUCKET.needs_input.color }} />
            Needs your input
          </span>
          <span className="bucket-n">{input.length}</span>
          <span className="bucket-sub">
            {input.length === 0
              ? "Nothing waiting on you"
              : [
                  questions && `${questions} supplier question${questions === 1 ? "" : "s"}`,
                  drafts && `${drafts} follow-up${drafts === 1 ? "" : "s"} to approve`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
          </span>
          <span className="bucket-go">Review →</span>
        </button>

        <button className="bucket" onClick={() => onOpen("working")}>
          <span className="bucket-title">
            <span className="swatch" style={{ background: BUCKET.working.color }} />
            Agent working
          </span>
          <span className="bucket-n">{working.length}</span>
          <span className="bucket-sub">
            {working.length === 0 ? (
              "Nothing in progress"
            ) : (
              <span className="clock-list">
                {(["overdue", "due_soon", "on_track", "pending"] as const)
                  .filter((k) => clocks[k])
                  .map((k) => (
                    <span key={k} className={`clock ${k}`}>
                      <ClockIcon status={k} />
                      {clocks[k]} {CLOCK_LABEL[k]}
                    </span>
                  ))}
              </span>
            )}
          </span>
          <span className="bucket-go">Track follow-ups →</span>
        </button>
      </div>

      <div className="home-grid">
        <section className="panel">
          <h3 className="panel-title">Where your quotes stand</h3>
          <Pipeline counts={counts} total={entries.length} onOpen={onOpen} />
          <h3 className="panel-title sub-title">By part</h3>
          <PartProgress parts={parts} onOpenPart={onOpenPart} />
          <p className="muted totals">
            {entries.length} supplier quote{entries.length === 1 ? "" : "s"} across {rfqs} RFQ
            {rfqs === 1 ? "" : "s"}, {partCount} part{partCount === 1 ? "" : "s"} and {suppliers} supplier
            {suppliers === 1 ? "" : "s"}
          </p>
        </section>

        <section className="panel">
          <h3 className="panel-title">Needs attention</h3>
          {attention.length === 0 ? (
            <p className="muted">All clear.</p>
          ) : (
            <ul className="attention">
              {attention.map((e) => {
                const part = partOf(e);
                const status: ClockStatus | "pending" =
                  e.reason === "question" ? "overdue" : e.followUp?.status ?? "pending";
                const what =
                  e.reason === "question" ? "asked you a question"
                    : e.reason === "approve_draft" ? "follow-up draft waiting for you"
                    : e.followUp?.status === "overdue" ? `no reply — overdue since ${shortDate(e.followUp.due)}`
                    : `reply due ${shortDate(e.followUp?.due)}`;
                return (
                  <li key={e.key}>
                    <button className="attention-row" onClick={() => part && onOpenPart(part)} disabled={!part}>
                      <ClockIcon status={e.reason === "approve_draft" ? "pending" : status} />
                      <span>
                        <strong>{e.supplier}</strong>
                        <span className="muted-inline"> · {part ?? e.reference}</span>
                        <span className="sub">{what}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
