import type { Part } from "../data";
import { offerLabel } from "./PriceBreakChart";
import { seriesColor } from "./palette";

/**
 * Lead time per offer, in calendar days, on one shared scale. Each bar keeps
 * the colour its offer has in the price chart, so a buyer can match "cheapest"
 * to "fastest" across the two at a glance. The value sits at the bar's tip,
 * with the supplier's own wording underneath.
 */
export default function LeadTimeBars({ part }: { part: Part }) {
  const bars = part.rows
    .map((row, i) => ({ row, color: seriesColor(i), label: offerLabel(row) }))
    .filter(({ row }) => row.leadDays != null);

  if (!bars.length) return null;

  const max = Math.max(...bars.map((b) => b.row.leadDays!));
  const fastest = Math.min(...bars.map((b) => b.row.leadDays!));
  const compared = bars.length > 1;

  return (
    <figure className="chart">
      <figcaption>
        <span className="chart-title">Lead time</span>
        <span className="chart-sub">calendar days</span>
      </figcaption>
      <ul className="bars">
        {bars.map(({ row, color, label }) => {
          const days = row.leadDays!;
          return (
            <li key={label} className="bar-row">
              <span className="bar-label">{label}</span>
              <span className="bar-track">
                <span
                  className="bar"
                  // Scaled within the track minus room for the label, so the
                  // longest bar's value still sits outside it rather than on top.
                  style={{ width: `calc(${Math.max(days / max, 0.02)} * (100% - 7.5rem))`, background: color }}
                />
                <span className="bar-value">
                  {days} days
                  {compared && days === fastest && <span className="bar-flag">fastest</span>}
                </span>
              </span>
              {row.leadText && row.leadText !== `${days} days` && <span className="bar-raw">{row.leadText}</span>}
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
