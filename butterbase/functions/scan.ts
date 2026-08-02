// One RFQ thread per invocation: fetch the inbox, take the oldest unseen
// message, run one coordinator session, record it, exit.
//
// Deliberately not a batch. Functions cap at 300s and a session runs 30-60s, so
// batching five threads sat at ~80% of the ceiling and a busier inbox would die
// mid-run. One thread per call is well inside the limit and self-paces on a
// cron; agent_seen is what makes that safe across invocations.
//
// Anthropic hosts the agent loop. Everything with a credential or a side effect
// -- Graph reads, Graph replies, the comparison table -- runs here.
import Anthropic from "npm:@anthropic-ai/sdk";

// Rewritten to true by deploy-functions.py for the /fn/trigger deployment.
const IS_TRIGGER = false;

const GRAPH = "https://graph.microsoft.com/v1.0";
const AUTH_ROOT = "https://login.microsoftonline.com";
const SCOPES = "offline_access User.Read Mail.Read Mail.Send";

type Msg = {
  message_id: string;
  thread_id: string;
  subject: string;
  sender: string;
  recipients: string;
  sent_at: string;
  body_text: string;
};

// ── Microsoft Graph ───────────────────────────────────────────────────────────

async function accessToken(env: Record<string, string>): Promise<string> {
  const tenant = env.FORGEFLOW_AZURE_TENANT_ID || "consumers";
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: env.FORGEFLOW_AZURE_CLIENT_ID,
    refresh_token: env.FORGEFLOW_OUTLOOK_REFRESH_TOKEN,
    scope: SCOPES,
  });
  if (env.FORGEFLOW_AZURE_CLIENT_SECRET) body.set("client_secret", env.FORGEFLOW_AZURE_CLIENT_SECRET);

  const res = await fetch(`${AUTH_ROOT}/${tenant}/oauth2/v2.0/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    throw new Error(`Outlook login expired -- re-run login-outlook. ${await res.text()}`);
  }
  return (await res.json()).access_token;
}

function htmlToText(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

async function fetchRecent(token: string, top: number): Promise<Msg[]> {
  const select = [
    "id", "conversationId", "subject", "from", "toRecipients",
    "receivedDateTime", "body", "bodyPreview", "webLink",
  ].join(",");
  const query = new URLSearchParams({
    $top: String(top),
    $orderby: "receivedDateTime desc",
    $select: select,
  });
  const res = await fetch(`${GRAPH}/me/mailFolders/Inbox/messages?${query}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Graph ${res.status}: ${await res.text()}`);

  return ((await res.json()).value ?? []).map((m: any) => {
    const body = m.body ?? {};
    const raw = body.content ?? m.bodyPreview ?? "";
    return {
      message_id: m.id,
      thread_id: m.conversationId || m.id,
      subject: (m.subject || "(no subject)").trim(),
      sender: m.from?.emailAddress?.address ?? "",
      recipients: (m.toRecipients ?? []).map((r: any) => r.emailAddress?.address).join(", "),
      sent_at: m.receivedDateTime,
      body_text: (body.contentType ?? "").toLowerCase() === "html" ? htmlToText(raw) : raw.trim(),
    };
  });
}

async function replyTo(token: string, messageId: string, comment: string): Promise<void> {
  const res = await fetch(`${GRAPH}/me/messages/${encodeURIComponent(messageId)}/reply`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ comment }),
  });
  if (!res.ok) throw new Error(`Graph reply ${res.status}: ${await res.text()}`);
}

// ── Comparison table ──────────────────────────────────────────────────────────

function rows(result: any): any[] {
  return result?.rows ?? (Array.isArray(result) ? result : []);
}

async function readTable(db: any, reference: string): Promise<string> {
  const rfqs = rows(await db.query(
    "select id, thread_id, subject, status, collection_form, updated_at from rfqs " +
      "order by updated_at desc limit 5",
  ));
  if (!rfqs.length) {
    return "The comparison table is empty — nothing has been collected for this RFQ yet.";
  }
  const quotes = rows(await db.query(
    "select rfq_id, supplier_name, supplier_email, status, extracted, missing_fields " +
      "from supplier_quotes order by updated_at desc",
  ));
  const needle = (reference || "").toLowerCase();
  let shaped = rfqs.map((r: any) => ({
    ...r,
    supplier_quotes: quotes.filter((q: any) => q.rfq_id === r.id),
  }));
  if (needle) {
    const matched = shaped.filter((r: any) => (r.subject ?? "").toLowerCase().includes(needle));
    if (matched.length) shaped = matched;
  }
  return JSON.stringify(shaped, null, 2);
}

async function recordExtraction(db: any, thread: Msg, input: any): Promise<string> {
  const supplier = input.supplier_name || "unknown supplier";
  const classification = input.classification || "unknown";
  const extraction = input.extraction ?? {};

  await db.query(
    `insert into rfqs (id, thread_id, subject, buyer_email, status, collection_form, updated_at)
     values ($1, $1, $2, $3, $4, $5::jsonb, now())
     on conflict (id) do update set status = excluded.status,
       collection_form = coalesce(excluded.collection_form, rfqs.collection_form),
       updated_at = now()`,
    [
      thread.thread_id,
      thread.subject,
      thread.recipients || null,
      classification,
      classification === "rfq_sent" ? JSON.stringify(extraction) : null,
    ],
  );

  if (classification === "supplier_quote" || classification === "supplier_reminder") {
    await db.query(
      `insert into supplier_quotes (id, rfq_id, thread_id, supplier_email, supplier_name,
         status, extracted, latest_message_id, updated_at)
       values ($1, $2, $2, $3, $4, $5, $6::jsonb, $7, now())
       on conflict (rfq_id, supplier_email) do update set
         supplier_name = excluded.supplier_name, status = excluded.status,
         extracted = excluded.extracted, latest_message_id = excluded.latest_message_id,
         updated_at = now()`,
      [
        `${thread.thread_id}|${thread.sender.toLowerCase()}`,
        thread.thread_id,
        thread.sender,
        input.supplier_name ?? null,
        classification,
        JSON.stringify(extraction),
        thread.message_id,
      ],
    );
  }
  return `Recorded ${supplier} into the comparison table.`;
}

// ── Handler ───────────────────────────────────────────────────────────────────

export async function handler(request: Request, context: any): Promise<Response> {
  const env = context.env ?? {};
  const db = context.db;

  // This same source is deployed twice. As /fn/scan it is cron-driven and its
  // HTTP trigger stays auth:required. As /fn/trigger it is reachable from the
  // dashboard, so it authenticates itself against a key the operator holds --
  // platform auth does not exist on this app, and an open endpoint that can
  // send mail from the mailbox is not acceptable. Fails closed: no key
  // configured means the trigger refuses everything.
  //
  // IS_TRIGGER is rewritten to true at deploy time for the trigger copy. An
  // earlier version sniffed request.url for "/trigger", which never matched --
  // so the gate was skipped and the endpoint ran a full scan unauthenticated.
  if (IS_TRIGGER) {
    const expected = env.FORGEFLOW_TRIGGER_KEY;
    const supplied = request.headers.get("x-forgeflow-key") ?? "";
    if (!expected) {
      return Response.json(
        { error: "FORGEFLOW_TRIGGER_KEY is not set, so manual triggering is disabled." },
        { status: 503 },
      );
    }
    if (supplied !== expected) {
      return Response.json({ error: "Bad or missing x-forgeflow-key." }, { status: 401 });
    }
  }
  const autosend = String(env.FORGEFLOW_MANAGED_AGENT_AUTOSEND ?? "").toLowerCase();
  const sending = ["1", "true", "yes"].includes(autosend);

  const missing = ["ANTHROPIC_API_KEY", "FORGEFLOW_OUTLOOK_REFRESH_TOKEN",
    "FORGEFLOW_AZURE_CLIENT_ID", "FORGEFLOW_AGENT_ID", "FORGEFLOW_ENV_ID"]
    .filter((k) => !env[k]);
  if (missing.length) {
    return Response.json({ error: "missing env", missing }, { status: 500 });
  }

  const token = await accessToken(env);
  const messages = await fetchRecent(token, Number(env.FORGEFLOW_OUTLOOK_TOP ?? 10));
  if (!messages.length) return Response.json({ processed: 0, reason: "inbox empty" });

  const seen = new Set(
    rows(await db.query("select message_id from agent_seen")).map((r: any) => r.message_id),
  );
  // Oldest first: a backlog should drain in the order it arrived.
  const pending = messages
    .filter((m) => !seen.has(m.message_id))
    .sort((a, b) => a.sent_at.localeCompare(b.sent_at));
  if (!pending.length) return Response.json({ processed: 0, reason: "nothing new" });

  const target = pending[0];
  const thread = messages
    .filter((m) => m.thread_id === target.thread_id)
    .sort((a, b) => a.sent_at.localeCompare(b.sent_at));

  // Keep the raw thread, so the dashboard can show what the agent actually read
  // rather than only its conclusions. Insert-only: emails do not change.
  for (const m of thread) {
    await db.query(
      `insert into interactions (message_id, thread_id, subject, sender, recipients,
         sent_at, body_text, source_path)
       values ($1, $2, $3, $4, $5, $6, $7, $8)
       on conflict (message_id) do nothing`,
      [m.message_id, m.thread_id, m.subject, m.sender, m.recipients,
       m.sent_at, m.body_text, `graph:${m.message_id}`],
    );
  }

  const threadText = [
    `RFQ email thread (subject: ${target.subject}):`, "",
    ...thread.flatMap((m) => [
      `--- message_id: ${m.message_id}`, `From: ${m.sender}`, `Sent: ${m.sent_at}`, "",
      m.body_text, "",
    ]),
    "Handle the latest message in this thread.",
  ].join("\n");

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
  const session = await client.beta.sessions.create({
    agent: env.FORGEFLOW_AGENT_ID,
    environment_id: env.FORGEFLOW_ENV_ID,
    title: "RFQ thread triage",
  });

  const actions: string[] = [];
  // The session id is a positional path parameter in the TS SDK -- passing it
  // inside the options object yields "path with invalid segments".
  const stream = await client.beta.sessions.events.stream(session.id);
  await client.beta.sessions.events.send(session.id, {
    events: [{ type: "user.message", content: [{ type: "text", text: threadText }] }],
  });

  for await (const event of stream) {
    if (event.type === "agent.custom_tool_use") {
      let result: string;
      try {
        if (event.name === "read_comparison_table") {
          result = await readTable(db, event.input?.rfq_reference ?? "");
        } else if (event.name === "record_extraction") {
          result = await recordExtraction(db, target, event.input ?? {});
          actions.push(`recorded:${event.input?.supplier_name ?? "?"}`);
        } else if (event.name === "send_reply") {
          const mid = event.input?.message_id;
          if (!mid) {
            result = "No message_id was given, so nothing was sent.";
          } else if (!sending) {
            result = "Draft recorded. Not sent — autosend is disabled.";
            actions.push("drafted");
          } else {
            await replyTo(token, mid, event.input?.body_text ?? "");
            result = "Reply sent.";
            actions.push("sent");
          }
        } else {
          result = `Unknown tool ${event.name}.`;
        }
      } catch (e) {
        // Tell the agent the truth rather than claiming a write that failed.
        result = `Tool ${event.name} failed: ${String(e).slice(0, 300)}`;
      }
      const reply: any = {
        type: "user.custom_tool_result",
        custom_tool_use_id: event.id,
        content: [{ type: "text", text: result }],
      };
      // Subagent tool calls are cross-posted here; answer on their thread.
      if (event.session_thread_id) reply.session_thread_id = event.session_thread_id;
      await client.beta.sessions.events.send(session.id, { events: [reply] });
    } else if (event.type === "session.status_idle") {
      if (event.stop_reason?.type === "requires_action") continue;
      break;
    } else if (event.type === "session.status_terminated") {
      break;
    }
  }

  await db.query(
    `insert into agent_seen (message_id, session_id, sent_reply, processed_at)
     values ($1, $2, $3, now())
     on conflict (message_id) do update set session_id = excluded.session_id,
       sent_reply = excluded.sent_reply, processed_at = now()`,
    [target.message_id, session.id, actions.includes("sent")],
  );

  return Response.json({
    processed: 1,
    remaining: pending.length - 1,
    thread_id: target.thread_id,
    subject: target.subject,
    session_id: session.id,
    autosend: sending,
    actions,
  });
}
