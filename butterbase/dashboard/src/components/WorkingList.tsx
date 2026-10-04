import { FOLLOW_UP_BUSINESS_DAYS, shortDate } from "../data";
import type { QuoteEntry } from "../data";

/** Overdue first, then by how little time is left; not-yet-chased last. */
const urgency = (e: QuoteEntry) => (e.followUp ? e.followUp.daysLeft : Number.POSITIVE_INFINITY);

function Status({ e }: { e: QuoteEntry }) {
  const f = e.followUp;
  if (!f) return <span className="clock pending">Follow-up not sent yet</span>;
  if (f.status === "overdue") {
    const late = -f.daysLeft;
    return (
      <span className="clock overdue">
        Overdue{late > 0 ? ` ${late} business day${late === 1 ? "" : "s"}` : ""} — chase again
      </span>
    );
  }
  return (
    <span className={`clock ${f.status}`}>
      {f.daysLeft} business day{f.daysLeft === 1 ? "" : "s"} left
    </span>
  );
}

export default function WorkingList({
  entries,
  partOf,
  onOpenPart,
}: {
  entries: QuoteEntry[];
  partOf: (e: QuoteEntry) => string | null;
  onOpenPart: (partNumber: string) => void;
}) {
  if (!entries.length) return <p className="empty">The agent has nothing in progress.</p>;

  const sorted = [...entries].sort((a, b) => urgency(a) - urgency(b));

  return (
    <>
      <p className="muted">
        Suppliers get {FOLLOW_UP_BUSINESS_DAYS} business days to answer a follow-up. Most urgent
        first.
      </p>
      <div className="scroll">
        <table className="list">
          <thead>
            <tr>
              <th>Part / RFQ</th>
              <th>Supplier</th>
              <th>Waiting for</th>
              <th>Follow-up sent</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((e) => {
              const part = partOf(e);
              return (
                <tr key={e.key}>
                  <td>
                    {part ? (
                      <button className="link" onClick={() => onOpenPart(part)}>
                        {part}
                      </button>
                    ) : (
                      e.reference
                    )}
                  </td>
                  <td>{e.supplier}</td>
                  <td className="muted">{e.missing.join(", ") || "—"}</td>
                  <td>{e.followUp ? shortDate(e.followUp.sentAt) : "—"}</td>
                  <td>
                    <Status e={e} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
