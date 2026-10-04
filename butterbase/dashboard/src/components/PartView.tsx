import { shortDate, sourcesOf } from "../data";
import type { Part, QuoteStateKey } from "../data";
import LeadTimeBars from "../charts/LeadTimeBars";
import PriceBreakChart from "../charts/PriceBreakChart";
import { seriesColor } from "../charts/palette";
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
  const suppliers = new Set(part.rows.map((r) => r.entry.supplier)).size;
  const ready = part.rows.filter((r) => r.entry.state === "ready").length;
  const bestPriceRow = part.bestPrice
    ? part.rows.find((r) => r.prices.get(part.bestPrice!.qty)?.value === part.bestPrice!.value)
    : undefined;
  const fastestRow = part.rows.find((r) => r.leadDays != null && r.leadDays === part.bestLeadDays);

  return (
    <div className="panel">
      <header className="detail-head">
        <div>
          <p className="eyebrow">Part</p>
          <h2>{part.partNumber}</h2>
          {(part.description || part.manufacturer) && (
            <p className="muted">{[part.description, part.manufacturer].filter(Boolean).join(" · ")}</p>
          )}
        </div>
        <p className="muted">Last quoted {shortDate(part.lastQuoted)}</p>
      </header>

      <div className="tiles">
        <div className="tile">
          <span className="tile-label">Best unit price</span>
          <span className="tile-value">{part.bestPrice?.text ?? "—"}</span>
          <span className="tile-sub">
            {part.bestPrice
              ? `${part.bestPrice.qty ? `at ${Number(part.bestPrice.qty).toLocaleString()} pcs · ` : ""}${
                  bestPriceRow ? bestPriceRow.entry.supplier : ""}`
              : "No price yet"}
          </span>
        </div>
        <div className="tile">
          <span className="tile-label">Fastest lead time</span>
          <span className="tile-value">{part.bestLeadDays != null ? `${part.bestLeadDays} days` : "—"}</span>
          <span className="tile-sub">{fastestRow ? fastestRow.entry.supplier : "No lead time yet"}</span>
        </div>
        <div className="tile">
          <span className="tile-label">Offers</span>
          <span className="tile-value">{part.rows.length}</span>
          <span className="tile-sub">
            from {suppliers} supplier{suppliers === 1 ? "" : "s"} · {ready} complete
          </span>
        </div>
      </div>

      <div className="charts">
        <PriceBreakChart part={part} />
        <LeadTimeBars part={part} />
      </div>

      <h3 className="panel-title">All offers</h3>
      <div className="scroll">
        <table className="compare">
          <thead>
            <tr>
              <th>Supplier</th>
              <th>Tier</th>
              {part.quantities.map((q) => (
                <th key={q} className="num">
                  {q ? `${Number(q).toLocaleString()} pcs` : "Unit price"}
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
            {part.rows.map((row, i) => {
              const isBestLead =
                compared && row.leadDays != null && row.leadDays === part.bestLeadDays;
              return (
                <tr key={`${row.entry.key}|${row.tier ?? ""}`}>
                  <td>
                    <span className="swatch" style={{ background: seriesColor(i) }} />
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
                    {row.leadText && row.leadText !== `${row.leadDays} days` && <span className="sub">{row.leadText}</span>}
                  </td>
                  <td className="nowrap">{row.moq ?? DASH}</td>
                  <td>{row.nre ?? DASH}</td>
                  <td className="nowrap">{row.validUntil ?? DASH}</td>
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
