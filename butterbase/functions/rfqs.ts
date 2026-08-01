// Dashboard read model: every RFQ with its suppliers, flattened enough that the
// UI can render a comparison without a second round trip per row.
//
// This runs server-side so the service key never reaches a browser. The frontend
// calls this function; it does not talk to the Data API directly.
export async function handler(request: Request, context: any): Promise<Response> {
  const url = new URL(request.url);
  const limit = Number(url.searchParams.get("limit") ?? 25);

  const rfqs = await context.db.query(
    "select id, thread_id, subject, buyer_email, status, collection_form, updated_at " +
      "from rfqs order by updated_at desc limit $1",
    [limit],
  );

  const quotes = await context.db.query(
    "select id, rfq_id, supplier_name, supplier_email, status, extracted, " +
      "missing_fields, latest_message_id, updated_at from supplier_quotes " +
      "order by updated_at desc",
  );

  const rows = (rfqs?.rows ?? rfqs ?? []) as any[];
  const quoteRows = (quotes?.rows ?? quotes ?? []) as any[];

  const payload = rows.map((rfq) => ({
    ...rfq,
    supplier_quotes: quoteRows.filter((q) => q.rfq_id === rfq.id),
  }));

  return new Response(JSON.stringify({ rfqs: payload }), {
    headers: { "content-type": "application/json" },
  });
}
