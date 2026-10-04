import { useState } from "react";
import type { Part, PartRow } from "../data";
import { niceTicks, seriesColor, useWidth } from "./palette";

const HEIGHT = 260;
const M = { top: 16, right: 34, bottom: 34, left: 58 };

export const offerLabel = (row: PartRow) =>
  row.tier ? `${row.entry.supplier} · ${row.tier}` : row.entry.supplier;

/** Decimal places the data itself uses, so $0.384 is not shown as $0.38. */
function decimalsOf(texts: string[]): number {
  let max = 2;
  for (const t of texts) {
    const m = t.match(/\.(\d+)/);
    if (m) max = Math.max(max, m[1].length);
  }
  return Math.min(max, 4);
}

/**
 * Unit price against quantity, one line per offer (supplier and tier). This is
 * the view a buyer needs to see where suppliers cross over: who is cheapest at
 * prototype volume versus at production volume. Quantities are evenly spaced
 * breaks rather than a linear axis, because the breaks are what was quoted.
 */
export default function PriceBreakChart({ part }: { part: Part }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const qtys = part.quantities.filter((q) => q !== "");
  const series = part.rows
    .map((row, i) => ({ row, color: seriesColor(i), label: offerLabel(row) }))
    .filter(({ row }) => qtys.some((q) => row.prices.get(q)?.value != null));

  if (qtys.length < 2 || !series.length) return null;

  const values = series.flatMap(({ row }) =>
    qtys.map((q) => row.prices.get(q)?.value).filter((v): v is number => v != null),
  );
  const texts = series.flatMap(({ row }) => [...row.prices.values()].map((c) => c.text));
  const decimals = decimalsOf(texts);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const [y0, y1] = [ticks[0], ticks[ticks.length - 1]];

  const w = Math.max(width, 280);
  const innerW = w - M.left - M.right;
  const innerH = HEIGHT - M.top - M.bottom;
  const x = (i: number) => M.left + (qtys.length === 1 ? innerW / 2 : (i / (qtys.length - 1)) * innerW);
  const y = (v: number) => M.top + innerH - ((v - y0) / (y1 - y0 || 1)) * innerH;
  const money = (v: number) => `$${v.toFixed(decimals)}`;
  const band = innerW / Math.max(qtys.length - 1, 1);

  /** Path through consecutive quoted breaks; a skipped break leaves a gap. */
  const pathOf = (row: PartRow) => {
    let d = "";
    let pen = false;
    qtys.forEach((q, i) => {
      const v = row.prices.get(q)?.value;
      if (v == null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  return (
    <figure className="chart">
      <figcaption>
        <span className="chart-title">Unit price by quantity</span>
        <ul className="legend">
          {series.map((s) => (
            <li key={s.label}>
              <svg width="18" height="8" aria-hidden="true">
                <line x1="1" y1="4" x2="17" y2="4" stroke={s.color} strokeWidth="2" strokeLinecap="round" />
              </svg>
              {s.label}
            </li>
          ))}
        </ul>
      </figcaption>

      <div ref={ref} className="chart-area" onPointerLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={w} height={HEIGHT} role="img" aria-label={`Unit price by quantity for ${part.partNumber}`}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="grid" x1={M.left} x2={w - M.right} y1={y(t)} y2={y(t)} />
                <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                  {money(t)}
                </text>
              </g>
            ))}
            <line className="axis" x1={M.left} x2={w - M.right} y1={M.top + innerH} y2={M.top + innerH} />
            {qtys.map((q, i) => (
              <text key={q} className="tick" x={x(i)} y={HEIGHT - 10} textAnchor="middle">
                {Number(q).toLocaleString()} pcs
              </text>
            ))}

            {hover != null && (
              <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + innerH} />
            )}

            {series.map((s) => (
              <path key={s.label} d={pathOf(s.row)} fill="none" stroke={s.color} strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {series.map((s) =>
              qtys.map((q, i) => {
                const v = s.row.prices.get(q)?.value;
                if (v == null) return null;
                return (
                  <circle key={`${s.label}-${q}`} cx={x(i)} cy={y(v)} r={hover === i ? 5.5 : 4}
                    fill={s.color} stroke="var(--panel)" strokeWidth="2" />
                );
              }),
            )}

            {/* Hit bands: the reader aims at a quantity, never at a 2px line. */}
            {qtys.map((q, i) => (
              <rect key={q} x={x(i) - band / 2} y={M.top} width={band} height={innerH}
                fill="transparent" tabIndex={0} aria-label={`${Number(q).toLocaleString()} pcs`}
                onPointerEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} />
            ))}
          </svg>
        )}

        {hover != null && (
          <div
            className="tooltip"
            style={{
              left: x(hover) + 312 > w ? Math.max(x(hover) - 312, 0) : x(hover) + 12,
              top: M.top,
            }}
          >
            <div className="tooltip-head">{Number(qtys[hover]).toLocaleString()} pcs</div>
            {series.map((s) => {
              const cell = s.row.prices.get(qtys[hover]);
              return (
                <div key={s.label} className="tooltip-row">
                  <svg width="12" height="8" aria-hidden="true">
                    <line x1="1" y1="4" x2="11" y2="4" stroke={s.color} strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  <strong>{cell?.text ?? "—"}</strong>
                  <span>{s.label}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </figure>
  );
}
