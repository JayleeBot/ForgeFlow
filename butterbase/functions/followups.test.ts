// node --test butterbase/functions/followups.test.ts   (Node 23.6+ runs .ts directly)
import assert from "node:assert/strict";
import { afterEach, describe, mock, test } from "node:test";

import { addBusinessDays, followUpBody, followUpOn, handler, isDueToday } from "./followups.ts";

describe("business days", () => {
  test("skip weekends both ways", () => {
    assert.equal(addBusinessDays("2026-06-05", 1), "2026-06-08"); // Fri -> Mon
    assert.equal(addBusinessDays("2026-06-08", -2), "2026-06-04"); // Mon -> Thu
    assert.equal(addBusinessDays("2026-06-06", -2), "2026-06-04"); // Sat -> Thu
  });
});

describe("followUpOn", () => {
  test("2 business days before the due date", () => {
    // Sent Tue, due Sat: Thu.
    assert.equal(followUpOn("2026-06-02", "2026-06-06"), "2026-06-04");
  });
  test("on the due date when the RFQ left too little notice", () => {
    // Sent Thu, due Fri: two business days before is Wed, already past.
    assert.equal(followUpOn("2026-06-04", "2026-06-05"), "2026-06-05");
  });
  test("a weekend due date with too little notice moves back to Friday", () => {
    assert.equal(followUpOn("2026-06-04", "2026-06-07"), "2026-06-05");
  });
  test("an early chase on the sending day itself is too little notice", () => {
    // Sent Thu, due Mon: two business days before is Thu, the sending day.
    assert.equal(followUpOn("2026-06-04", "2026-06-08"), "2026-06-08");
  });
  test("3 business days after sending when there is no due date", () => {
    assert.equal(followUpOn("2026-06-04", null), "2026-06-09"); // Thu -> Tue
  });
});

describe("isDueToday", () => {
  test("from the follow-up day through 2 business days of catch-up", () => {
    assert.equal(isDueToday("2026-06-04", "2026-06-05"), false);
    assert.equal(isDueToday("2026-06-05", "2026-06-05"), true);
    assert.equal(isDueToday("2026-06-09", "2026-06-05"), true); // Fri + 2bd = Tue
    assert.equal(isDueToday("2026-06-10", "2026-06-05"), false);
  });
});

describe("followUpBody", () => {
  test("names both dates when there is a due date", () => {
    const body = followUpBody("2026-06-02", "2026-06-06");
    assert.match(body, /RFQ we sent on June 2, 2026\./);
    assert.match(body, /target response date is June 6, 2026/);
  });
  test("drops the target line without one", () => {
    assert.doesNotMatch(followUpBody("2026-06-02", null), /target response date/);
  });
});

// ── handler, against an in-memory stand-in for the tables it touches ──────────

type Row = Record<string, any>;

function fakeDb(rfqs: Row[], laterSenders: string[], followups: Row[] = []) {
  return {
    followups,
    async query(sql: string, params: any[] = []) {
      if (sql.includes("from rfqs r")) return { rows: rfqs };
      if (sql.includes("select 1 from rfq_followups")) {
        return { rows: followups.filter((f) => f.id === params[0]) };
      }
      if (sql.includes("from interactions")) {
        return { rows: laterSenders.filter((s) => s.split("@")[1] === params[1]).map(() => ({})) };
      }
      if (sql.startsWith("insert into rfq_followups")) {
        if (followups.some((f) => f.id === params[0])) return { rows: [] };
        followups.push({ id: params[0], due_date: params[3], follow_up_on: params[4], body: params[5], sent: false });
        return { rows: [{ id: params[0] }] };
      }
      if (sql.startsWith("update rfq_followups")) {
        followups.find((f) => f.id === params[0])!.sent = true;
        return { rows: [] };
      }
      if (sql.startsWith("delete from rfq_followups")) {
        followups.splice(followups.findIndex((f) => f.id === params[0]), 1);
        return { rows: [] };
      }
      throw new Error(`unexpected query: ${sql}`);
    },
  };
}

const RFQ = {
  rfq_id: "thread-1",
  due: "2026-06-06",
  message_id: "rfq-msg",
  sender: "s.kim@electester.com",
  recipients: "sales@magnatech-supply.com, colleague@electester.com",
  sent_at: "2026-06-02T01:30:00Z",
};
const ENV = {
  FORGEFLOW_AZURE_CLIENT_ID: "client",
  FORGEFLOW_OUTLOOK_REFRESH_TOKEN: "refresh",
};

function run(db: any, env: Row = {}) {
  return handler(new Request("https://fn.test/followups", { method: "POST" }), { env, db })
    .then((r) => r.json());
}

describe("handler", () => {
  afterEach(() => mock.reset());
  const onDay = () => mock.timers.enable({ apis: ["Date"], now: new Date("2026-06-04T14:00:00Z") });

  test("drafts once for the supplier, never for the buyer's own domain", async () => {
    onDay();
    const db = fakeDb([RFQ], []);
    const first = await run(db);
    assert.deepEqual(first.followups.map((f: Row) => [f.supplier, f.action]),
      [["sales@magnatech-supply.com", "drafted"]]);
    assert.equal(db.followups[0].sent, false);
    const second = await run(db);
    assert.equal(second.followups.length, 0);
  });

  test("a reply from the supplier's domain, from any address, stops the chase", async () => {
    onDay();
    const res = await run(fakeDb([RFQ], ["jun@magnatech-supply.com"]));
    assert.equal(res.followups.length, 0);
  });

  test("not before the follow-up day", async () => {
    mock.timers.enable({ apis: ["Date"], now: new Date("2026-06-03T14:00:00Z") });
    assert.equal((await run(fakeDb([RFQ], []))).followups.length, 0);
  });

  test("autosend replies all on the RFQ and marks it sent", async () => {
    onDay();
    const calls: string[] = [];
    mock.method(globalThis, "fetch", async (url: string) => {
      calls.push(String(url));
      return String(url).includes("/token")
        ? Response.json({ access_token: "tok" })
        : new Response(null, { status: 202 });
    });
    const db = fakeDb([RFQ], []);
    const res = await run(db, { ...ENV, FORGEFLOW_MANAGED_AGENT_AUTOSEND: "true" });
    assert.equal(res.followups[0].action, "sent");
    assert.ok(calls.some((u) => u.endsWith("/me/messages/rfq-msg/replyAll")));
    assert.equal(db.followups[0].sent, true);
  });

  test("a failed send releases the claim so the next run retries", async () => {
    onDay();
    mock.method(globalThis, "fetch", async (url: string) =>
      String(url).includes("/token")
        ? Response.json({ access_token: "tok" })
        : new Response("boom", { status: 500 }));
    const db = fakeDb([RFQ], []);
    const res = await run(db, { ...ENV, FORGEFLOW_MANAGED_AGENT_AUTOSEND: "true" });
    assert.equal(res.followups[0].action, "failed");
    assert.equal(db.followups.length, 0);
  });

  test("no due date: 3 business days after sending", async () => {
    mock.timers.enable({ apis: ["Date"], now: new Date("2026-06-05T14:00:00Z") });
    const res = await run(fakeDb([{ ...RFQ, due: null }], []));
    assert.equal(res.followups[0].follow_up_on, "2026-06-05");
  });
});
