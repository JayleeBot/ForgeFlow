// Dashboard read model: every RFQ with its suppliers, the raw email thread the
// agent read, and the agent runs that touched it.
//
// Runs server-side so the service key never reaches a browser. The frontend
// calls this function; it does not talk to the Data API directly.
export async function handler(request: Request, context: any): Promise<Response> {
  const url = new URL(request.url);
  const limit = Number(url.searchParams.get("limit") ?? 25);
  const rows = (r: any) => r?.rows ?? (Array.isArray(r) ? r : []);

  const rfqs = rows(await context.db.query(
    "select id, thread_id, subject, buyer_email, status, collection_form, updated_at " +
      "from rfqs order by updated_at desc limit $1",
    [limit],
  ));

  const quotes = rows(await context.db.query(
    "select id, rfq_id, supplier_name, supplier_email, status, extracted, " +
      "missing_fields, latest_message_id, updated_at from supplier_quotes " +
      "order by updated_at desc",
  ));

  // The emails themselves, so the dashboard can show what the agent read.
  const messages = rows(await context.db.query(
    "select message_id, thread_id, subject, sender, recipients, sent_at, body_text, " +
      "draft_reply from interactions order by sent_at asc",
  ));

  // Which agent run handled which message, and whether it replied. Joined so a
  // run can be attributed to a thread -- agent_seen only knows message ids.
  const runs = rows(await context.db.query(
    "select s.message_id, s.session_id, s.sent_reply, s.processed_at, i.thread_id " +
      "from agent_seen s left join interactions i on i.message_id = s.message_id " +
      "order by s.processed_at desc",
  ));

  const payload = rfqs.map((rfq: any) => ({
    ...rfq,
    supplier_quotes: quotes.filter((q: any) => q.rfq_id === rfq.id),
    messages: messages.filter((m: any) => m.thread_id === rfq.thread_id),
    runs: runs.filter((r: any) => r.thread_id === rfq.thread_id),
  }));

  return new Response(
    JSON.stringify({
      rfqs: payload,
      // Runs whose message predates thread capture have no thread to attach to.
      unattributed_runs: runs.filter((r: any) => !r.thread_id).length,
    }),
    { headers: { "content-type": "application/json" } },
  );
}
