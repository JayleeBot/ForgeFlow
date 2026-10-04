import { shortDate } from "../data";
import type { Part } from "../data";

/** One line per part: enough to pick which one to open, nothing more. */
export default function PartTable({
  parts,
  onOpen,
  empty,
}: {
  parts: Part[];
  onOpen: (partNumber: string) => void;
  empty: string;
}) {
  if (!parts.length) return <p className="empty">{empty}</p>;

  return (
    <div className="scroll">
      <table className="list">
        <thead>
          <tr>
            <th>Part #</th>
            <th>Suppliers</th>
            <th>Best price</th>
            <th>Best lead time</th>
            <th>Last quoted</th>
          </tr>
        </thead>
        <tbody>
          {parts.map((p) => {
            const suppliers = new Set(p.rows.map((r) => r.entry.supplier)).size;
            return (
              <tr key={p.partNumber} className="clickable" onClick={() => onOpen(p.partNumber)}>
                <td>
                  {/* The row is clickable; the button is there for keyboard users. */}
                  <button
                    className="link"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpen(p.partNumber);
                    }}
                  >
                    {p.partNumber}
                  </button>
                  {p.manufacturer && <span className="sub">{p.manufacturer}</span>}
                </td>
                <td>{suppliers}</td>
                <td className="num">
                  {p.bestPrice ? (
                    <>
                      {p.bestPrice.text}
                      {p.bestPrice.qty && <span className="sub">at {p.bestPrice.qty} pcs</span>}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="num">{p.bestLeadDays != null ? `${p.bestLeadDays} days` : "—"}</td>
                <td>{shortDate(p.lastQuoted)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
