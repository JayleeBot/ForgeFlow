import { shortDate } from "../data";
import type { QuoteEntry } from "../data";

/**
 * What is blocked on the buyer, and what to do about each one: answer a
 * supplier's question, or approve the follow-up the agent drafted.
 */
export default function InputList({
  entries,
  partOf,
  onOpenPart,
}: {
  entries: QuoteEntry[];
  partOf: (e: QuoteEntry) => string | null;
  onOpenPart: (partNumber: string) => void;
}) {
  if (!entries.length) return <p className="empty">Nothing is waiting on you.</p>;

  // Supplier questions first: a supplier who asked is stalled until answered.
  const sorted = [...entries].sort(
    (a, b) => Number(b.reason === "question") - Number(a.reason === "question"),
  );

  return (
    <ul className="cards">
      {sorted.map((e) => {
        const part = partOf(e);
        return (
          <li key={e.key} className="card">
            <div className="card-head">
              <span>
                <strong>{e.supplier}</strong>
                <span className="muted"> · {part ?? e.reference}</span>
              </span>
              <span className="tag">
                {e.reason === "question" ? "Supplier question" : "Approve follow-up"}
              </span>
            </div>

            {e.reason === "question" ? (
              <p className="quote-text">
                {e.question ?? "The supplier is waiting on your answer before they can finish the quote."}
              </p>
            ) : (
              <>
                <p className="muted">
                  The agent drafted a follow-up asking for{" "}
                  {e.missing.length ? e.missing.join(", ") : "the outstanding details"}. It has not
                  been sent.
                </p>
                {e.draft && (
                  <details className="inline">
                    <summary>Show draft</summary>
                    <div className="msg-body">{e.draft}</div>
                  </details>
                )}
              </>
            )}

            <div className="card-foot">
              <span className="muted">Quoted {shortDate(e.quotedAt)}</span>
              {part && (
                <button className="link" onClick={() => onOpenPart(part)}>
                  Open {part} →
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
