// Sample data for the public demo. Every company, person, part number and price
// here is invented. Dates are generated relative to the moment the page opens,
// so the follow-up clocks always show a live mix of on-track, due-soon and
// overdue instead of going stale the week after a deploy.
//
// The scenario covers every state the dashboard renders:
//   PCB-4417-A  three suppliers, one quoting two tiers: a real price comparison
//   SHF-2210    two complete, one still chasing (due soon)
//   IC-5521     one complete with a long lead time, one chasing (on track)
//   CON-7781    one draft waiting for the buyer, one overdue
//   ENC-0930    one complete, one supplier asking the buyer a question

import type { Message, PriceBreak, Rfq, Run, Snapshot } from "./types";

const BUYER = "dana.whitfield@acme-robotics.example";

type Offer = {
  tier?: string;
  lead: string | null;
  prices: (string | null)[];
};

type DemoQuote = {
  supplier: string;
  email: string;
  contact: string;
  offers: Offer[];
  moq?: string;
  nre?: string;
  coo?: string;
  terms?: string;
  valid?: string;
  missing?: (string | { missing: string; part_number: string; service_tier?: string })[];
  question?: string;
  /** Business days ago the agent's follow-up went out; absent means none was sent. */
  followUpDaysAgo?: number;
  /** A follow-up the agent drafted but has not sent (autosend off). */
  draft?: string;
  /** Business days ago the supplier replied. */
  repliedDaysAgo: number;
};

type DemoRfq = {
  reference: string;
  part: string;
  description: string;
  manufacturer?: string;
  quantities: number[];
  sentDaysAgo: number;
  quotes: DemoQuote[];
};

const RFQS: DemoRfq[] = [
  {
    reference: "RFQ-2026-0412",
    part: "PCB-4417-A",
    description: "6-layer motor controller PCB, FR-4, ENIG, 1.6 mm",
    quantities: [100, 500, 1000],
    sentDaysAgo: 12,
    quotes: [
      {
        supplier: "Northgate Circuits",
        email: "quotes@northgate-circuits.example",
        contact: "Priya Raman",
        offers: [
          { tier: "Standard", lead: "15 business days", prices: ["$14.20", "$9.85", "$8.10"] },
          { tier: "Quick Turn", lead: "5 business days", prices: ["$22.60", "$16.40", "$14.90"] },
        ],
        moq: "50 pcs",
        nre: "$450 tooling",
        coo: "Taiwan",
        terms: "Net 30",
        valid: "30 days",
        repliedDaysAgo: 6,
      },
      {
        supplier: "Bayline PCB",
        email: "sales@baylinepcb.example",
        contact: "Marcus Lee",
        offers: [{ tier: "Standard", lead: "4 weeks", prices: ["$12.90", "$10.20", "$7.65"] }],
        moq: "100 pcs",
        nre: "$600 one-time",
        coo: "China",
        terms: "Net 45",
        valid: "60 days",
        repliedDaysAgo: 5,
      },
      {
        supplier: "Orion Electronics Mfg",
        email: "rfq@orion-em.example",
        contact: "Elena Torres",
        offers: [{ tier: "Standard", lead: "3 weeks", prices: ["$15.75", "$9.40", "$8.35"] }],
        moq: "25 pcs",
        nre: "None",
        coo: "USA",
        terms: "Net 30",
        valid: "45 days",
        repliedDaysAgo: 4,
      },
    ],
  },
  {
    reference: "RFQ-2026-0415",
    part: "SHF-2210",
    description: "Precision drive shaft, 17-4 PH stainless, ±0.005 mm",
    quantities: [50, 250, 1000],
    sentDaysAgo: 11,
    quotes: [
      {
        supplier: "Halvorsen Precision",
        email: "estimating@halvorsen.example",
        contact: "Jonas Halvorsen",
        offers: [{ tier: "Standard", lead: "25 business days from PO", prices: ["$18.40", "$15.75", "$12.85"] }],
        moq: "50 pcs",
        nre: "$2,400 one-time",
        coo: "USA",
        terms: "Net 30",
        valid: "30 days",
        repliedDaysAgo: 5,
      },
      {
        supplier: "Kestrel Machining",
        email: "quotes@kestrel-mach.example",
        contact: "Sofia Mendez",
        offers: [
          { tier: "Standard", lead: "6 weeks", prices: ["$17.10", "$14.90", "$13.20"] },
          { tier: "Expedited", lead: "2 weeks", prices: ["$24.80", "$21.30", "$19.60"] },
        ],
        moq: "100 pcs",
        nre: "$1,800 one-time",
        coo: "Mexico",
        terms: "Net 45",
        valid: "30 days",
        repliedDaysAgo: 3,
      },
      {
        supplier: "Tri-County CNC",
        email: "office@tricountycnc.example",
        contact: "Bill Okafor",
        offers: [{ tier: "Standard", lead: "30 days", prices: ["$19.20", "$16.05", "$13.40"] }],
        moq: "50 pcs",
        nre: "$950",
        valid: "30 days",
        missing: ["payment_terms", "coo"],
        followUpDaysAgo: 2,
        repliedDaysAgo: 4,
      },
    ],
  },
  {
    reference: "RFQ-2026-0419",
    part: "IC-5521",
    description: "32-bit MCU, 256 KB flash, LQFP-64",
    manufacturer: "Meridian Semiconductor",
    quantities: [250, 1000, 2500],
    sentDaysAgo: 9,
    quotes: [
      {
        supplier: "Arrowfield Distribution",
        email: "rfq@arrowfield.example",
        contact: "Grace Kim",
        offers: [{ lead: "26 weeks", prices: ["$4.82", "$4.31", "$3.96"] }],
        moq: "250 pcs (full reel)",
        nre: "None",
        coo: "Malaysia",
        terms: "Net 30",
        valid: "14 days",
        repliedDaysAgo: 3,
      },
      {
        supplier: "Brightline Components",
        email: "sales@brightline.example",
        contact: "Omar Haddad",
        offers: [{ lead: "18 weeks", prices: ["$4.65", "$4.20", null] }],
        moq: "250 pcs",
        coo: "Malaysia",
        terms: "Net 30",
        valid: "14 days",
        missing: [{ missing: "unit_price", part_number: "IC-5521 at 2500 pcs" }, "nre"],
        followUpDaysAgo: 0,
        repliedDaysAgo: 1,
      },
    ],
  },
  {
    reference: "RFQ-2026-0421",
    part: "CON-7781",
    description: "Board-to-wire connector, 12-pos, 2.0 mm pitch",
    quantities: [1000, 5000, 10000],
    sentDaysAgo: 10,
    quotes: [
      {
        supplier: "Pinnacle Interconnect",
        email: "quotes@pinnacle-ic.example",
        contact: "Hannah Brooks",
        offers: [{ lead: "8 weeks", prices: ["$0.384", "$0.341", "$0.318"] }],
        nre: "None",
        coo: "Vietnam",
        terms: "Net 30",
        missing: ["moq", "quote_valid_until"],
        draft:
          "Hi Hannah,\n\nThank you for the quote on CON-7781. To complete our comparison, could you " +
          "confirm:\n\n- The minimum order quantity\n- How long these prices are valid\n\nBest regards,\n" +
          "Dana Whitfield\nAcme Robotics Procurement",
        repliedDaysAgo: 1,
      },
      {
        supplier: "Vantage Components",
        email: "rfq@vantage-comp.example",
        contact: "Luis Ortega",
        offers: [{ lead: null, prices: ["$0.402", "$0.355", null] }],
        moq: "1,000 pcs",
        coo: "China",
        terms: "Net 60",
        valid: "30 days",
        missing: ["lead_time", { missing: "unit_price", part_number: "CON-7781 at 10000 pcs" }],
        followUpDaysAgo: 5,
        repliedDaysAgo: 7,
      },
    ],
  },
  {
    reference: "RFQ-2026-0423",
    part: "ENC-0930",
    description: "Injection-molded enclosure, PC/ABS, UL94 V-0",
    quantities: [500, 2000],
    sentDaysAgo: 8,
    quotes: [
      {
        supplier: "Summit Molding",
        email: "estimating@summitmolding.example",
        contact: "Rachel Nguyen",
        offers: [{ lead: "10 weeks", prices: ["$3.85", "$2.95"] }],
        moq: "500 pcs",
        nre: "$18,500 tooling (Class B aluminum)",
        coo: "USA",
        terms: "50% tooling deposit, Net 30",
        valid: "60 days",
        repliedDaysAgo: 2,
      },
      {
        supplier: "Moldcraft Plastics",
        email: "j.liu@moldcraft.example",
        contact: "Jason Liu",
        offers: [{ lead: null, prices: [null, null] }],
        coo: "China",
        missing: ["buyer_input_required", "unit_price", "nre"],
        question:
          "Could you confirm the tooling grade: Class A hardened steel (500k+ shots) or Class B " +
          "aluminum (~50k shots)? Price and NRE depend on it.",
        repliedDaysAgo: 1,
      },
    ],
  },
];

const iso = (d: Date) => d.toISOString();

/** `n` business days before `now`, at a plausible time of day. */
function businessDaysAgo(now: Date, n: number, hour: number): Date {
  const d = new Date(now);
  let left = n;
  while (left > 0) {
    d.setDate(d.getDate() - 1);
    if (d.getDay() !== 0 && d.getDay() !== 6) left -= 1;
  }
  d.setHours(hour, 15, 0, 0);
  // Never in the future, even for "0 days ago" when the page opens early.
  return d > now ? new Date(now.getTime() - 60 * 60 * 1000) : d;
}

const fieldText = (m: NonNullable<DemoQuote["missing"]>[number]) =>
  (typeof m === "string" ? m : `${m.missing} (${m.part_number})`).replace(/_/g, " ");

function priceLines(rfq: DemoRfq, q: DemoQuote): string {
  return q.offers
    .map((o) => {
      const rows = rfq.quantities
        .map((qty, i) => (o.prices[i] ? `  ${qty} pcs: ${o.prices[i]} each` : null))
        .filter(Boolean)
        .join("\n");
      return `${o.tier ? `${o.tier}:\n` : ""}${rows}${o.lead ? `\n  Lead time: ${o.lead}` : ""}`;
    })
    .join("\n\n");
}

function supplierReply(rfq: DemoRfq, q: DemoQuote): string {
  if (q.question) return `Hi Dana,\n\nThanks for the RFQ. ${q.question}\n\nRegards,\n${q.contact}\n${q.supplier}`;
  const terms = [
    q.moq && `MOQ: ${q.moq}`,
    q.nre && `NRE: ${q.nre}`,
    q.coo && `Country of origin: ${q.coo}`,
    q.terms && `Payment terms: ${q.terms}`,
    q.valid && `Valid for: ${q.valid}`,
  ]
    .filter(Boolean)
    .join("\n");
  return `Hi Dana,\n\nPlease see our quote for ${rfq.part}:\n\n${priceLines(rfq, q)}\n\n${terms}\n\nRegards,\n${q.contact}\n${q.supplier}`;
}

export function demoSnapshot(now: Date): Snapshot {
  const rfqs: Rfq[] = [];

  for (const rfq of RFQS) {
    for (const q of rfq.quotes) {
      const threadId = `demo-${rfq.reference}-${q.email.split("@")[0]}`.toLowerCase();
      const sent = businessDaysAgo(now, rfq.sentDaysAgo, 9);
      const replied = businessDaysAgo(now, q.repliedDaysAgo, 14);
      const followUp = q.followUpDaysAgo != null ? businessDaysAgo(now, q.followUpDaysAgo, 11) : null;
      const updated = followUp && followUp > replied ? followUp : replied;
      const subject = `${rfq.reference} — ${rfq.part} ${rfq.description.split(",")[0]}`;
      const first = q.contact.split(" ")[0];

      const price_breaks: PriceBreak[] = q.offers
        .flatMap((o) =>
          rfq.quantities.map((quantity, i) => ({
            part_number: rfq.part,
            service_tier: o.tier ?? null,
            quantity,
            unit_price: o.prices[i],
            lead_time: o.lead,
          })),
        )
        .filter((b) => b.unit_price != null);

      const messages: Message[] = [
        {
          message_id: `${threadId}-1`,
          thread_id: threadId,
          subject,
          sender: BUYER,
          recipients: q.email,
          sent_at: iso(sent),
          body_text:
            `Hi ${first},\n\nPlease quote ${rfq.part} (${rfq.description}) at ` +
            `${rfq.quantities.join(" / ")} pcs. Include unit price, lead time, MOQ, NRE, country of ` +
            `origin, payment terms and quote validity.\n\nThanks,\nDana Whitfield\nAcme Robotics Procurement`,
        },
        {
          message_id: `${threadId}-2`,
          thread_id: threadId,
          subject: `Re: ${subject}`,
          sender: q.email,
          recipients: BUYER,
          sent_at: iso(replied),
          body_text: supplierReply(rfq, q),
          draft_reply: q.draft ?? null,
        },
      ];

      if (followUp) {
        messages.push({
          message_id: `${threadId}-3`,
          thread_id: threadId,
          subject: `Re: ${subject}`,
          sender: BUYER,
          recipients: q.email,
          sent_at: iso(followUp),
          body_text:
            `Hi ${first},\n\nThank you for the quote. Could you also confirm: ` +
            `${(q.missing ?? []).map(fieldText).join(", ")}?` +
            `\n\nBest regards,\nDana Whitfield\nAcme Robotics Procurement`,
        });
      }

      const runs: Run[] = [
        {
          message_id: `${threadId}-2`,
          thread_id: threadId,
          session_id: null,
          sent_reply: followUp != null,
          processed_at: iso(followUp ?? replied),
        },
      ];

      rfqs.push({
        id: threadId,
        thread_id: threadId,
        subject,
        buyer_email: BUYER,
        status: "supplier_quote",
        collection_form: null,
        updated_at: iso(updated),
        supplier_quotes: [
          {
            id: `${threadId}|${q.email}`,
            rfq_id: threadId,
            supplier_name: q.supplier,
            supplier_email: q.email,
            status: "supplier_quote",
            updated_at: iso(updated),
            missing_fields: null,
            extracted: {
              rfq_requirements: {
                our_part_number: rfq.part,
                manufacturer: rfq.manufacturer ?? null,
                quantities_requested: rfq.quantities,
              },
              supplier_quote: {
                supplier_name: q.supplier,
                rfq_reference: rfq.reference,
                manufacturer: rfq.manufacturer ?? null,
                description: rfq.description,
                price_breaks,
                moq: q.moq ?? null,
                nre: q.nre ?? null,
                coo: q.coo ?? null,
                payment_terms: q.terms ?? null,
                quote_valid_until: q.valid ?? null,
                blocking_question: q.question ?? null,
                missing_fields: { per_part: [], quote_level: q.missing ?? [] },
              },
            },
          },
        ],
        messages,
        runs,
      });
    }
  }

  return {
    captured_at: iso(now),
    trigger_url: null,
    rfqs: rfqs.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at))),
  };
}
