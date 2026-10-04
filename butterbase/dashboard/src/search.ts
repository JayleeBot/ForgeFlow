import type { Part } from "./data";

/**
 * Everything a buyer might search a part by, flattened into one lowercase
 * haystack: the part number and manufacturer, and for each supplier row the
 * supplier's name and email and the RFQ it was quoted on (reference, thread id,
 * subject).
 */
export function searchableText(part: Part): string {
  const bits: (string | null | undefined)[] = [part.partNumber, part.manufacturer];
  for (const { entry } of part.rows) {
    bits.push(
      entry.supplier,
      entry.quote.supplier_email,
      entry.reference,
      entry.thread.id,
      entry.thread.subject,
    );
  }
  return bits.filter(Boolean).join(" ").toLowerCase();
}

/** Case-insensitive substring match; every whitespace-separated term must hit. */
export function matches(haystack: string, query: string): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return terms.every((t) => haystack.includes(t));
}
