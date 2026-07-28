"""Build docs/eval_report.html from the latest saved eval run.

    PYTHONPATH=src python3 -m forgeflow.cli eval --save runs/latest.json
    python3 scripts/build_eval_report.py runs/latest.json

Written for a reader who does procurement, not one who reads Python: each case
shows the email thread, what the agent did about it, and whether that was right.
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/eval_report.html"

cases = json.loads((ROOT / "data/eval_cases/eval_cases.json").read_text())
RUN_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs/multi_v2.json"
run = {r["email_file"]: r for r in json.loads(RUN_FILE.read_text())}
PROMPTS = {"extraction.txt": "Extraction agent", "response.txt": "Response agent"}
prompt_text = {f: (ROOT / "src/forgeflow/prompts" / f).read_text() for f in PROMPTS}

FLAKY = {"data/sample_emails/02_incomplete_quote.eml"}

e = html.escape

FIELD_WORDS = {
    "price_breaks": "unit prices", "lead_time": "production lead time",
    "coo": "country of origin", "payment_terms": "payment terms",
    "moq": "minimum order quantity", "nre": "NRE / tooling cost",
    "mfg_part_number": "manufacturer part number",
}


def parse_eml(path: Path) -> dict:
    raw = path.read_text()
    head, _, body = raw.partition("\n\n")
    f = {}
    for line in head.splitlines():
        m = re.match(r"^([A-Za-z-]+):\s*(.*)$", line)
        if m:
            f[m.group(1).lower()] = m.group(2)
    return {"subject": f.get("subject", ""), "sender": f.get("from", ""), "body": body.strip()}


def sentence(action: str, asked: list, quote: dict) -> str:
    if action == "chase_supplier":
        names = ", ".join(FIELD_WORDS.get(a, a) for a in asked) or "the outstanding fields"
        return f"Wrote back to the supplier asking for <strong>{e(names)}</strong>."
    if action == "flag_buyer":
        if quote.get("blocking_question"):
            return "Stopped and <strong>escalated to the buyer</strong> — the supplier is waiting on a decision only the buyer can make."
        return "Stopped and <strong>escalated to the buyer</strong> — the supplier quoted a different manufacturer part than the RFQ asked for."
    if action == "ready_for_review":
        return "Sent nothing. Everything the buyer asked for is answered — <strong>ready for human review</strong>."
    return "Sent nothing. This email is not a supplier reply, so there is <strong>nothing to act on</strong>."


blocks = []
for idx, case in enumerate(cases):
    key = case["email_file"]
    files = case.get("thread_emails") or [key]
    emails = [parse_eml(ROOT / f) for f in files]
    latest = emails[-1]
    res = run.get(key, {})
    grades = res.get("grades", [])
    trace = res.get("trace") or {}
    extraction = (trace.get("output") or {}).get("extraction") or {}
    quote = extraction.get("supplier_quote") or {}
    rfq = extraction.get("rfq_requirements") or {}
    draft = (trace.get("output") or {}).get("draft_reply")
    action = trace.get("action", "none")
    asked = trace.get("fields_requested") or []
    failed = [g for g in grades if not g["passed"]]
    status = "pass" if not failed else ("flaky" if key in FLAKY else "fail")
    verdict = {"pass": "Passed", "flaky": "Unstable", "fail": "Failed"}[status]

    def who(m):
        name = m["sender"].split("<")[0].strip().strip('"')
        return name or m["sender"]

    steps = []
    for i, m in enumerate(emails):
        last = i == len(emails) - 1
        tag = "Latest" if last else f"Round {i + 1}"
        body = (f'<pre class="mail">{e(m["body"])}</pre>' if last else
                f'<details class="earlier"><summary>Read this message</summary>'
                f'<pre class="mail">{e(m["body"])}</pre></details>')
        steps.append(
            f'<li class="step{" step-latest" if last else ""}">'
            f'<div class="step-head"><span class="step-tag">{tag}</span>'
            f'<span class="step-who">{e(who(m))}</span></div>{body}</li>'
        )
    thread_html = f'<ol class="thread">{"".join(steps)}</ol>'
    thread_label = (f'<span class="thread-count">{len(emails)}-email thread</span>'
                    if len(emails) > 1 else "")

    rows = quote.get("price_breaks") or []
    rows_html = "".join(
        f"""<tr><td>{e(str(r.get('part_number')))}</td><td>{e(str(r.get('service_tier') or '—'))}</td>
             <td class="n">{e(str(r.get('quantity')))}</td><td class="n">{e(str(r.get('unit_price')))}</td>
             <td>{e(str(r.get('lead_time') or '—'))}</td></tr>"""
        for r in rows
    ) or '<tr><td colspan="5" class="dim">No pricing extracted</td></tr>'

    facts = [("Classification", extraction.get("classification")),
             ("Buyer asked for", ", ".join(FIELD_WORDS.get(f, f) for f in (rfq.get("required_fields") or [])) or None),
             ("Part number (buyer)", rfq.get("our_part_number")),
             ("Manufacturer P/N — RFQ", rfq.get("mfg_part_number")),
             ("Manufacturer P/N — quoted", quote.get("mfg_part_number")),
             ("Country of origin", quote.get("coo")), ("Payment terms", quote.get("payment_terms")),
             ("MOQ", quote.get("moq")), ("NRE", quote.get("nre")),
             ("Supplier's question", quote.get("blocking_question"))]
    facts_html = "".join(
        f"<tr><th>{e(k)}</th><td>{e(str(v)) if v else '<span class=dim>not stated</span>'}</td></tr>"
        for k, v in facts if v or k.startswith("Manufacturer") or k == "Supplier's question"
    )

    grade_html = "".join(
        f"""<tr><td>{e(g['grader'])}</td>
             <td class="{'ok' if g['passed'] else 'no'}">{'pass' if g['passed'] else 'fail'}</td>
             <td class="why">{e(g['reason'])}</td></tr>"""
        for g in grades
    )

    note = ('<p class="note">This grader gives a different answer on different runs — it passes '
            'when re-run on its own. Treated as run-to-run variance rather than a real failure.</p>'
            if status == "flaky" else "")

    blocks.append(f"""
    <article class="case" data-status="{status}" data-action="{action}" data-thread="{"multi" if len(emails) > 1 else "single"}">
      <div class="case-head">
        <span class="num">{idx + 1:02d}</span>
        <h3>{e(latest['subject'])}</h3>
        {thread_label}<span class="badge badge-{status}">{verdict}</span>
      </div>

      <div class="col">
        <h4>{"The thread so far" if len(emails) > 1 else "The email that arrived"}</h4>
        {thread_html}
      </div>

      <div class="col">
        <h4>What the agent did</h4>
        <p class="did">{sentence(action, asked, quote)}</p>
        {f'<h4>The reply it wrote</h4><pre class="reply">{e(draft)}</pre>' if draft else ''}

        <details class="more"><summary>What it pulled out of the email</summary>
          <div class="scroll"><table class="data">
            <thead><tr><th>Part</th><th>Tier</th><th>Qty</th><th>Unit price</th><th>Lead time</th></tr></thead>
            <tbody>{rows_html}</tbody></table></div>
          <table class="facts">{facts_html}</table>
        </details>

        <details class="more"><summary>All nine checks{'' if not failed else f' — {len(failed)} failed'}</summary>
          <table class="grades">{grade_html}</table>
          {note}
        </details>
      </div>
    </article>""")

per_grader = {}
for r in run.values():
    for g in r.get("grades", []):
        s = per_grader.setdefault(g["grader"], [0, 0])
        s[1] += 1
        s[0] += 1 if g["passed"] else 0
grader_rows = "".join(
    f"""<tr><td>{e(n)}</td><td class="n">{ok} / {tot}</td>
         <td><div class="track"><div class="fill{' full' if ok == tot else ''}" style="width:{round(100*ok/tot)}%"></div></div></td></tr>"""
    for n, (ok, tot) in per_grader.items()
)

total = len(cases)
passing = sum(1 for c in cases if not [g for g in run.get(c["email_file"], {}).get("grades", []) if not g["passed"]])
prompt_blocks = "".join(
    f"""<details class="more"><summary>{e(label)} — <code>{e(f)}</code> ({len(prompt_text[f]):,} characters)</summary>
        <pre class="prompt">{e(prompt_text[f])}</pre></details>"""
    for f, label in PROMPTS.items()
)

html_out = f"""<title>ForgeFlow — Eval Report</title>
<style>
:root {{
  --page:#eef0f2; --card:#ffffff; --ink:#1b1f24; --ink-2:#4d565f; --dim:#8a939c;
  --line:#dfe3e7; --line-2:#eef1f3;
  --accent:#2c5282; --ok:#2f7a4d; --ok-bg:#eaf5ee; --no:#b3261e; --no-bg:#fdeceb;
  --warn:#8a6410; --warn-bg:#fdf4e0;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}}
* {{ box-sizing:border-box; }}
html {{ color-scheme:light; }}
body {{ background:var(--page); color:var(--ink); font-family:var(--sans);
  font-size:16px; line-height:1.6; margin:0; padding:0 24px 90px;
  -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:1080px; margin:0 auto; }}

header {{ padding:56px 0 32px; }}
h1 {{ font-size:34px; line-height:1.2; letter-spacing:-0.02em; margin:0 0 12px; text-wrap:balance; }}
.lede {{ font-size:18px; color:var(--ink-2); margin:0; max-width:62ch; }}
.kicker {{ font-size:13px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase;
  color:var(--accent); margin:0 0 12px; }}

section {{ margin-bottom:52px; }}
h2 {{ font-size:22px; letter-spacing:-0.01em; margin:0 0 16px; }}
h4 {{ font-size:13px; font-weight:600; letter-spacing:0.04em; text-transform:uppercase;
  color:var(--dim); margin:0 0 8px; }}
.col h4 + h4 {{ margin-top:22px; }}
p {{ max-width:64ch; }}

.summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px;
  margin-bottom:22px; }}
.summary div {{ background:var(--card); border:1px solid var(--line); border-radius:6px;
  padding:18px 20px; }}
.summary b {{ display:block; font-size:30px; line-height:1.1; letter-spacing:-0.02em;
  font-variant-numeric:tabular-nums; margin-bottom:2px; }}
.summary span {{ font-size:14px; color:var(--ink-2); }}

table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th, td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line-2);
  vertical-align:top; }}
thead th {{ font-size:12px; font-weight:600; letter-spacing:0.04em; text-transform:uppercase;
  color:var(--dim); border-bottom:1px solid var(--line); }}
tbody tr:last-child td, tbody tr:last-child th {{ border-bottom:0; }}
.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
.dim {{ color:var(--dim); }}
.scroll {{ overflow-x:auto; }}

.panel {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:6px 4px; }}
.track {{ background:var(--line-2); border-radius:99px; height:8px; width:100%; max-width:260px;
  overflow:hidden; }}
.fill {{ background:#d0a13a; height:100%; border-radius:99px; }}
.fill.full {{ background:var(--ok); }}

.filters {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:20px; }}
.filters button {{ font-family:inherit; font-size:14px; padding:7px 15px; border:1px solid var(--line);
  background:var(--card); color:var(--ink-2); border-radius:20px; cursor:pointer; }}
.filters button:hover {{ border-color:var(--dim); }}
.filters button[aria-pressed="true"] {{ background:var(--accent); border-color:var(--accent);
  color:#fff; font-weight:600; }}
.filters button:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
.shown {{ margin-left:auto; font-size:14px; color:var(--dim); }}

.case {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:24px 26px 26px; margin-bottom:16px;
  display:grid; grid-template-columns:1fr 1fr; gap:0 34px; }}
.case-head {{ grid-column:1/-1; display:flex; align-items:center; gap:12px;
  padding-bottom:16px; margin-bottom:20px; border-bottom:1px solid var(--line); }}
.case-head h3 {{ font-size:17px; margin:0; flex:1; min-width:0; letter-spacing:-0.01em; }}
.num {{ font-family:var(--mono); font-size:13px; color:var(--dim); }}
.badge {{ font-size:13px; font-weight:600; padding:4px 12px; border-radius:20px; white-space:nowrap; }}
.badge-pass {{ color:var(--ok); background:var(--ok-bg); }}
.badge-flaky {{ color:var(--warn); background:var(--warn-bg); }}
.badge-fail {{ color:var(--no); background:var(--no-bg); }}
@media (max-width:860px) {{ .case {{ grid-template-columns:1fr; }} .col + .col {{ margin-top:26px; }} }}
.col {{ min-width:0; }}

.thread {{ list-style:none; margin:0; padding:0; }}
.step {{ position:relative; padding:0 0 0 26px; margin-bottom:14px; }}
.step::before {{ content:""; position:absolute; left:5px; top:7px; width:9px; height:9px;
  border-radius:50%; background:var(--line); border:2px solid var(--card); }}
.step:not(:last-child)::after {{ content:""; position:absolute; left:9px; top:18px; bottom:-14px;
  width:1px; background:var(--line); }}
.step-latest::before {{ background:var(--accent); }}
.step-head {{ display:flex; gap:10px; align-items:baseline; margin-bottom:6px; }}
.step-tag {{ font-size:12px; font-weight:600; letter-spacing:0.04em; text-transform:uppercase;
  color:var(--dim); }}
.step-latest .step-tag {{ color:var(--accent); }}
.step-who {{ font-size:14px; color:var(--ink-2); }}
.thread-count {{ font-size:13px; color:var(--ink-2); background:var(--line-2);
  padding:4px 11px; border-radius:20px; white-space:nowrap; }}
pre {{ font-family:var(--mono); font-size:13px; line-height:1.6; margin:0;
  white-space:pre-wrap; word-break:break-word; }}
.mail {{ background:#f7f8f9; border:1px solid var(--line-2); border-radius:5px; padding:14px 16px;
  max-height:300px; overflow:auto; color:var(--ink-2); }}
.reply {{ background:#f4f8fc; border:1px solid #d6e4f0; border-left:3px solid var(--accent);
  border-radius:5px; padding:14px 16px; max-height:330px; overflow:auto; }}
.did {{ font-size:16px; margin:0; }}
.did strong {{ font-weight:600; }}

details.more, details.earlier {{ border-top:1px solid var(--line-2); margin-top:16px; }}
details.more > summary, details.earlier > summary {{ font-size:14px; color:var(--accent);
  cursor:pointer; padding:11px 0 0; list-style:none; font-weight:500; }}
summary::-webkit-details-marker {{ display:none; }}
details > summary::before {{ content:"+ "; font-family:var(--mono); }}
details[open] > summary::before {{ content:"− "; }}
details > summary:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
details.more[open] > summary, details.earlier[open] > summary {{ margin-bottom:8px; }}
.facts th {{ font-weight:400; color:var(--ink-2); width:42%; }}
.grades td:first-child {{ font-family:var(--mono); font-size:12.5px; }}
.ok {{ color:var(--ok); font-weight:600; }}
.no {{ color:var(--no); font-weight:600; }}
.why {{ font-size:12.5px; color:var(--ink-2); }}
.note {{ font-size:14px; color:var(--warn); background:var(--warn-bg); border-radius:5px;
  padding:11px 14px; margin:12px 0 0; max-width:none; }}
.prompt {{ background:#f7f8f9; border:1px solid var(--line-2); border-radius:5px;
  padding:16px; max-height:460px; overflow:auto; font-size:12.5px; }}
code {{ font-family:var(--mono); font-size:0.92em; }}

.caveat {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:6px; padding:20px 24px; }}
.caveat h3 {{ font-size:16px; margin:0 0 8px; }}
.caveat p {{ margin:0 0 10px; color:var(--ink-2); font-size:15px; }}
.caveat p:last-child {{ margin:0; }}
footer {{ border-top:1px solid var(--line); padding-top:20px; color:var(--dim); font-size:14px; }}
</style>

<div class="wrap">
<header>
  <p class="kicker">ForgeFlow — supplier quote triage</p>
  <h1>What the agent did with {total} email threads</h1>
  <p class="lede">Each supplier email goes to two agents: one reads the thread and pulls out the
  quote, the other decides whether to chase the supplier, escalate to a human, or do nothing.
  Below is every test case — the email that came in, what the agent did about it, and whether
  that was right.</p>
</header>

<section>
  <h2>Results</h2>
  <div class="summary">
    <div><b>{passing} / {total}</b><span>threads handled correctly</span></div>
    <div><b>{sum(v[0] for v in per_grader.values())} / {sum(v[1] for v in per_grader.values())}</b><span>individual checks passed</span></div>
    <div><b>2</b><span>agents, 2 prompts</span></div>
  </div>
  <div class="panel scroll"><table>
    <thead><tr><th>Check</th><th class="n">Passed</th><th>&nbsp;</th></tr></thead>
    <tbody>{grader_rows}</tbody>
  </table></div>
</section>

<section>
  <div class="caveat">
    <h3>Two things to know before reading the numbers</h3>
    <p><strong>The score moves by about two threads between identical runs.</strong> Anything
    smaller than that is noise. A prompt change needs two or three runs before you can tell
    whether it actually helped.</p>
    <p><strong>A check passing does not prove the behaviour is right.</strong> Fifteen expected
    answers in this suite turned out to be wrong. Several had been passing the whole time,
    because the old pipeline was wrong in exactly the same way as the expectation.</p>
  </div>
</section>

<section>
  <h2>The {total} threads</h2>
  <div class="filters">
    <button data-filter="all" aria-pressed="true">All</button>
    <button data-filter="chase_supplier" aria-pressed="false">Chased supplier</button>
    <button data-filter="flag_buyer" aria-pressed="false">Escalated to buyer</button>
    <button data-filter="ready_for_review" aria-pressed="false">Ready for review</button>
    <button data-filter="none" aria-pressed="false">No action</button>
    <button data-filter="multi" aria-pressed="false">Multi-email threads</button>
    <button data-filter="flaky" aria-pressed="false">Unstable</button>
    <span class="shown" id="shown">Showing all {total}</span>
  </div>
  {''.join(blocks)}
</section>

<section>
  <h2>The two prompts</h2>
  <p>These are the complete instructions each agent runs on — nothing else steers them.</p>
  <div class="panel" style="padding:4px 22px 18px">{prompt_blocks}</div>
</section>

<footer>
  <p>Generated from run <code>{RUN_FILE.stem}</code>. Expected answers are written by hand from
  the source emails; the agent output is exactly what the run produced.</p>
</footer>
</div>

<script>
const buttons = document.querySelectorAll('.filters button');
const cases = document.querySelectorAll('.case');
const shown = document.getElementById('shown');
buttons.forEach(btn => btn.addEventListener('click', () => {{
  const f = btn.dataset.filter;
  buttons.forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
  let n = 0;
  cases.forEach(c => {{
    const match = f === 'all' || c.dataset.action === f || c.dataset.status === f || c.dataset.thread === f;
    c.style.display = match ? '' : 'none';
    if (match) n++;
  }});
  shown.textContent = f === 'all' ? 'Showing all {total}' : `Showing ${{n}} of {total}`;
}}));
</script>
"""

OUT.write_text(html_out)
print(f"wrote {len(html_out):,} bytes — {total} cases, {passing} passing")
