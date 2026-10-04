import { shortDate, sourcesOf } from "../data";
import type { Part, QuoteStateKey } from "../data";
import { Runs, Thread } from "./Thread";

const STATE_LABEL: Record<QuoteStateKey, string> = {
  ready: "Ready",
  needs_input: "Needs your input",
  working: "Agent working",
};

const DASH = <span className="muted">—</span>;

/**
 * The part a buyer came for, compared across suppliers at a glance: one row per
 * supplier and tier, quantity breaks as columns, lead time in days. Only the
 * best value in each column is coloured; everything else stays quiet.
 */
export default function PartView({ part }: { part: Part }) {
  const bestAt = new Map<string, number>();
  for (const qty of part.quantities) {
    const values = part.rows
      .map((r) => r.prices.get(qty)?.value)
      .filter((v): v is number => v != null);
    if (values.length) bestAt.set(qty, Math.min(...values));
  }
  // Only call something "best" when there is something to beat.
  const compared = part.rows.length > 1;
  const { messages, runs } = sourcesOf(part);

  return (
    <div className="panel">
      <header className="detail-head">
        <div>
          <h2>{part.partNumber}</h2>
          {part.manufacturer && <p className="muted">{part.manufacturer}</p>}
        </div>
        <p className="muted">
          {part.rows.length} offer{part.rows.length === 1 ? "" : "s"} · last quoted{" "}
          {shortDate(part.lastQuoted)}
        </p>
      </header>

      <div className="scroll">
        <table className="compare">
          <thead>
            <tr>
              <th>Supplier</th>
              <th>Tier</th>
              {part.quantities.map((q) => (
                <th key={q} className="num">
                  {q ? `${q} pcs` : "Unit price"}
                </th>
              ))}
              <th className="num">Lead time</th>
              <th>MOQ</th>
              <th>NRE</th>
              <th>Valid until</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {part.rows.map((row) => {
              const isBestLead =
                compared && row.leadDays != null && row.leadDays === part.bestLeadDays;
              return (
                <tr key={`${row.entry.key}|${row.tier ?? ""}`}>
                  <td>
                    <strong>{row.entry.supplier}</strong>
                  </td>
                  <td>{row.tier ? <span className="tier">{row.tier}</span> : DASH}</td>
                  {part.quantities.map((q) => {
                    const cell = row.prices.get(q);
                    if (!cell) return <td key={q} className="num">{DASH}</td>;
                    const best = compared && cell.value != null && cell.value === bestAt.get(q);
                    return (
                      <td key={q} className={best ? "num best" : "num"}>
                        {cell.text}
                      </td>
                    );
                  })}
                  <td className={isBestLead ? "num best" : "num"}>
                    {row.leadDays != null ? `${row.leadDays} days` : DASH}
                    {row.leadText && <span className="sub">{row.leadText}</span>}
                  </td>
                  <td>{row.moq ?? DASH}</td>
                  <td>{row.nre ?? DASH}</td>
                  <td>{row.validUntil ?? DASH}</td>
                  <td>
                    <span className={`state ${row.entry.state}`}>{STATE_LABEL[row.entry.state]}</span>
                    {row.entry.missing.length > 0 && (
                      <span className="sub">Missing: {row.entry.missing.join(", ")}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!compared && (
        <p className="muted hint">Only one supplier has quoted this part so far.</p>
      )}

      <Thread messages={messages} />
      <Runs runs={runs} />
    </div>
  );
}
