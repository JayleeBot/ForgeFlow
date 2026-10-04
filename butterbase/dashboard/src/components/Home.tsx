import type { ClockStatus, QuoteEntry, QuoteStateKey } from "../data";

export type Bucket = QuoteStateKey;

const CLOCK_LABEL: Record<ClockStatus | "pending", string> = {
  on_track: "on track",
  due_soon: "due soon",
  overdue: "overdue",
  pending: "follow-up not sent yet",
};

/**
 * The landing view answers one question: whose move is it. Each supplier quote
 * sits in exactly one bucket, so the three numbers add up to the total.
 */
export default function Home({
  entries,
  partCount,
  onOpen,
}: {
  entries: QuoteEntry[];
  partCount: number;
  onOpen: (b: Bucket) => void;
}) {
  const of = (s: QuoteStateKey) => entries.filter((e) => e.state === s);
  const ready = of("ready");
  const input = of("needs_input");
  const working = of("working");

  const questions = input.filter((e) => e.reason === "question").length;
  const drafts = input.filter((e) => e.reason === "approve_draft").length;

  const clocks: Record<ClockStatus | "pending", number> = { overdue: 0, due_soon: 0, on_track: 0, pending: 0 };
  for (const e of working) clocks[e.followUp?.status ?? "pending"] += 1;

  const suppliers = new Set(entries.map((e) => e.supplier.toLowerCase())).size;
  const rfqs = new Set(entries.map((e) => e.reference.toLowerCase())).size;

  return (
    <>
      <div className="buckets">
        <button className="bucket" onClick={() => onOpen("ready")}>
          <span className="bucket-title">Ready for review</span>
          <span className="bucket-n">{ready.length}</span>
          <span className="bucket-sub">Quotes complete — compare and decide</span>
        </button>

        <button className="bucket" onClick={() => onOpen("needs_input")}>
          <span className="bucket-title">Needs your input</span>
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
        </button>

        <button className="bucket" onClick={() => onOpen("working")}>
          <span className="bucket-title">Agent working</span>
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
                      {clocks[k]} {CLOCK_LABEL[k]}
                    </span>
                  ))}
              </span>
            )}
          </span>
        </button>
      </div>

      <p className="muted totals">
        {entries.length} supplier quote{entries.length === 1 ? "" : "s"} · {rfqs} RFQ
        {rfqs === 1 ? "" : "s"} · {partCount} part{partCount === 1 ? "" : "s"} · {suppliers} supplier
        {suppliers === 1 ? "" : "s"}
      </p>
    </>
  );
}
