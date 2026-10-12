// Chase suppliers who have not answered an RFQ by its follow-up date (issue #4).
//
// scan.ts only acts on new mail, so a supplier who never replies never wakes it.
// This runs on a weekday clock instead. The decision is date arithmetic and the
// message is a fixed template -- no agent -- so it cannot invent a deadline, a
// field, or a price.
//
// When to chase, in business days (Mon-Fri, holidays not modelled):
//   - the RFQ names a response date: 2 business days before it
//   - that leaves no time after the RFQ went out: on the response date itself
//   - no response date: 3 business days after the RFQ went out
// A supplier counts as having replied when any stored email from their domain
// arrived after the RFQ, in this thread or any other. Each supplier on an RFQ
// is chased at most once; rfq_followups is the record of that.
//
// Sending follows the same switch as scan.ts: FORGEFLOW_MANAGED_AGENT_AUTOSEND.
// Off, the text is stored in rfq_followups and nothing goes out. Each run logs
// its result, which /logs shows: cron discards the response.

const GRAPH = "https://graph.microsoft.com/v1.0";
const AUTH_ROOT = "https://login.microsoftonline.com";
const SCOPES = "offline_access User.Read Mail.Read Mail.Send";

const LEAD_BUSINESS_DAYS = 2;
const DEFAULT_BUSINESS_DAYS = 3;
// A follow-up day missed (outage, failed send) is retried for this many business
// days, then dropped. Without a limit, the first deploy would chase every RFQ
// in the table, however old.
const CATCH_UP_BUSINESS_DAYS = 2;

// ── Business-day arithmetic, on YYYY-MM-DD strings in UTC ─────────────────────

function isWeekend(day: string): boolean {
  const dow = new Date(`${day}T00:00:00Z`).getUTCDay();
  return dow === 0 || dow === 6;
}

function shiftDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function addBusinessDays(day: string, n: number): string {
  const step = n < 0 ? -1 : 1;
  let left = Math.abs(n);
  let d = day;
  while (left > 0) {
    d = shiftDays(d, step);
    if (!isWeekend(d)) left -= 1;
  }
  return d;
}

export function followUpOn(sentOn: string, dueOn: string | null): string {
  if (!dueOn) return addBusinessDays(sentOn, DEFAULT_BUSINESS_DAYS);
  const early = addBusinessDays(dueOn, -LEAD_BUSINESS_DAYS);
  if (early > sentOn) return early;
  // Too little notice for an early chase: chase on the due date, or the
  // business day before it when it falls on a weekend.
  let d = dueOn;
  while (isWeekend(d)) d = shiftDays(d, -1);
  return d;
}

export function isDueToday(today: string, on: string): boolean {
  return today >= on && today <= addBusinessDays(on, CATCH_UP_BUSINESS_DAYS);
}

// ── Template ──────────────────────────────────────────────────────────────────

function longDate(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "long", day: "numeric", year: "numeric", timeZone: "UTC",
  });
}

export function followUpBody(sentOn: string, dueOn: string | null): string {
  // The supplier's contact name is not recorded anywhere for a supplier who
  // never replied, so the greeting stays generic rather than guessing one.
  const ask = "please let us know if you are able to provide a quote, or if you need any "
    + "additional information?";
  return [
    "Hello,",
    "",
    `I wanted to follow up on the RFQ we sent on ${longDate(sentOn)}.`,
    dueOn
      ? `Our target response date is ${longDate(dueOn)} — could you ${ask}`
      : `Could you ${ask}`,
    "",
    "Thank you,",
    "Procurement Team",
  ].join("\n");
}

// ── Microsoft Graph ───────────────────────────────────────────────────────────
// Duplicated from scan.ts: each function deploys as a single file.

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

// Reply-all on the buyer's RFQ, from the CC'd mailbox: the supplier gets it in
// the original thread and the buyer sees that the chase went out.
async function replyAll(token: string, messageId: string, comment: string): Promise<void> {
  const res = await fetch(`${GRAPH}/me/messages/${encodeURIComponent(messageId)}/replyAll`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ comment }),
  });
  if (!res.ok) throw new Error(`Graph replyAll ${res.status}: ${await res.text()}`);
}

// ── Handler ───────────────────────────────────────────────────────────────────

function rows(result: any): any[] {
  return result?.rows ?? (Array.isArray(result) ? result : []);
}

const domainOf = (email: string) => email.split("@")[1]?.trim().toLowerCase() ?? "";

export async function handler(request: Request, context: any): Promise<Response> {
  const env = context.env ?? {};
  const db = context.db;
  const autosend = String(env.FORGEFLOW_MANAGED_AGENT_AUTOSEND ?? "").toLowerCase();
  const sending = ["1", "true", "yes"].includes(autosend);
  const today = new Date().toISOString().slice(0, 10);

  // Only threads that began with the buyer's RFQ: collection_form is set on
  // rfq_sent alone. The thread's first stored email is that RFQ.
  const rfqs = rows(await db.query(
    `select r.id as rfq_id, r.collection_form->'rfq_requirements'->>'response_due_date' as due,
            i.message_id, i.sender, i.recipients, i.sent_at
       from rfqs r
       join lateral (
         select message_id, sender, recipients, sent_at from interactions
          where thread_id = r.id order by sent_at asc limit 1
       ) i on true
      where r.collection_form is not null`,
  ));

  const results: any[] = [];
  let token: string | null = null;

  for (const r of rfqs) {
    const sentOn = new Date(r.sent_at).toISOString().slice(0, 10);
    // A malformed date from extraction is treated as no date, not as a crash.
    const dueOn = /^\d{4}-\d{2}-\d{2}$/.test(r.due ?? "") ? r.due : null;
    const on = followUpOn(sentOn, dueOn);
    if (!isDueToday(today, on)) continue;

    // The buyer's own domain covers the buyer, colleagues and the CC'd agent.
    const buyerDomain = domainOf(r.sender);
    const suppliers = String(r.recipients ?? "").split(",").map((s) => s.trim().toLowerCase())
      .filter((e) => e.includes("@") && domainOf(e) !== buyerDomain);

    for (const supplier of suppliers) {
      const id = `${r.rfq_id}|${supplier}`;
      const already = rows(await db.query("select 1 from rfq_followups where id = $1", [id]));
      if (already.length) continue;
      const replied = rows(await db.query(
        `select 1 from interactions
          where sent_at > $1 and lower(split_part(sender, '@', 2)) = $2 limit 1`,
        [r.sent_at, domainOf(supplier)],
      ));
      if (replied.length) continue;

      const body = followUpBody(sentOn, dueOn);
      const entry: any = { rfq_id: r.rfq_id, supplier, due: dueOn, follow_up_on: on };
      results.push(entry);

      // Claim before sending, so an overlapping run cannot send the same chase.
      const claimed = rows(await db.query(
        `insert into rfq_followups (id, rfq_id, supplier_email, due_date, follow_up_on, body)
         values ($1, $2, $3, $4, $5, $6) on conflict (id) do nothing returning id`,
        [id, r.rfq_id, supplier, dueOn, on, body],
      ));
      if (!claimed.length) {
        entry.action = "claimed by another run";
        continue;
      }
      if (!sending) {
        entry.action = "drafted";
        continue;
      }
      try {
        token ??= await accessToken(env);
        await replyAll(token, r.message_id, body);
      } catch (e) {
        // Release the claim so the next run retries within the catch-up window.
        await db.query("delete from rfq_followups where id = $1", [id]);
        entry.action = "failed";
        entry.error = String(e).slice(0, 300);
        continue;
      }
      // Outside the try: once the mail is out, a failed update must not release
      // the claim, or tomorrow's run would send it again.
      await db.query("update rfq_followups set sent = true where id = $1", [id]);
      entry.action = "sent";
    }
  }

  const summary = { today, autosend: sending, checked: rfqs.length, followups: results };
  console.log(JSON.stringify(summary));
  return Response.json(summary);
}
