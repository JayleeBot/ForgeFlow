# Deploying ForgeFlow

Three ways to run the RFQ agent. They differ only in *where the host-side code
runs* — the agent itself always runs on Anthropic.

## What runs where

Anthropic hosts the agent loop: the coordinator decides how to classify a
thread, what to extract, and what to write. Everything with a credential or a
side effect runs on **your** side, as host-side tools:

| | |
|---|---|
| **Anthropic (Managed Agents)** | classify the thread, decide the action, write the reply prose |
| **Wherever you deploy** | Microsoft Graph reads, Graph replies, the comparison table |

That split is why the Outlook token and the database never enter Anthropic's
sandbox — and why every deployment target below needs the same credentials.

The three host-side tools are `read_comparison_table`, `record_extraction`, and
`send_reply`, defined in [`src/forgeflow/managed_agent.py`](../src/forgeflow/managed_agent.py).

## Choosing a target

| Target | Runs | Use it for | Cannot |
|---|---|---|---|
| **Butterbase** | cron, every 10 min | production; the dashboard's "Process new email" button | run longer than 300s per invocation |
| **GitHub Actions** | manual dispatch | ad-hoc runs, and keeping the Outlook token fresh | run on a schedule safely (see below) |
| **Docker** | continuous 60s poll | low-latency polling, or running inside your own network | nothing — but you host it |

**Today's production path is Butterbase.** Actions is kept alongside it for one
non-obvious reason documented under *Token rotation* below — do not delete it.

---

## 1. Butterbase (current production)

App `app_nkpie8ug8oun` · API `https://api.butterbase.ai/v1/app_nkpie8ug8oun` ·
site `https://forgeflow-rfq.butterbase.dev`

Platform quirks — schema format, the CORS trap, `timeoutMs`, the auth model —
live in [`butterbase/README.md`](../butterbase/README.md). This section is only
the deploy sequence.

### One-time

```bash
python butterbase/deploy.py --apply       # apply schema.json (dry run without --apply)
python butterbase/set-secrets.py --apply  # copy runtime secrets from .env
```

Set the non-secret identifiers once (`FORGEFLOW_AGENT_ID`, `FORGEFLOW_ENV_ID`,
`FORGEFLOW_OUTLOOK_TOP`) with a `PATCH /env` call — see the app-environment
section of the Butterbase README.

### Every deploy

```bash
python butterbase/deploy-functions.py     # scan (+cron), trigger, rfqs
python butterbase/deploy-frontend.py      # dashboard, with a data snapshot baked in
```

`deploy-functions.py` deploys `scan.ts` **twice**: as `scan` (cron every 10
minutes, HTTP `auth: required`) and as `trigger` (HTTP `auth: none`, gated
inside the handler by `x-forgeflow-key`). Both get `timeoutMs: 300000`.

### Agent configuration

The agents are Anthropic resources, deployed separately from Butterbase:

```bash
PYTHONPATH=src python3 -m forgeflow.managed_agent deploy   # push model/prompt/tool changes
PYTHONPATH=src python3 -m forgeflow.managed_agent health   # verify before running
```

`deploy` creates a new agent **version**. `scan.ts` passes the agent ID as a
bare string, which resolves to the latest version — so a `deploy` takes effect
on the next session with no function redeploy.

### Turning sending on and off

`FORGEFLOW_MANAGED_AGENT_AUTOSEND` in the app environment. Set to
`true`/`1`/`yes` and the agent emails suppliers unattended on every cron tick.
Anything else (including unset) drafts to the function log instead.

---

## 2. GitHub Actions

Two workflows, both manual-dispatch only:

| Workflow | What it runs |
|---|---|
| `Agent scan` | the managed agent — same code path as Butterbase |
| `Email scan` | the older deterministic pipeline (forgeflow's own rules draft the reply) |

### Configuration

**Secrets** — `ANTHROPIC_API_KEY`, `FORGEFLOW_OUTLOOK_REFRESH_TOKEN`,
`FORGEFLOW_AZURE_CLIENT_ID`, `BUTTERBASE_API_KEY`.

**Variables** — `FORGEFLOW_AGENT_ID`, `FORGEFLOW_REPLY_AGENT_ID`,
`FORGEFLOW_ENV_ID`, `BUTTERBASE_APP_URL`. These identify resources rather than
authenticating to them, so they are variables, not secrets.

Without `BUTTERBASE_API_KEY` the job silently falls back to SQLite on the runner
and its writes are discarded when the job ends.

### Token rotation — why this workflow still matters

Entra issues a **new** refresh token every time the old one is redeemed. The
`Hand the rotated token to Butterbase` step pushes that replacement into the
Butterbase app environment, server to server.

`scan.ts` does **not** do this — it refreshes the access token but never
persists the rotated refresh token back. So Butterbase's stored credential
ages, and today it is an Actions run that refreshes it.

**Run `Agent scan` periodically (or before the grace period lapses) until the
function persists its own rotation.** If Butterbase's token goes stale with no
Actions run to refresh it, recovery needs an interactive device login.

### Not on a schedule

Both workflows are `workflow_dispatch` only, deliberately. A runner starts with
no local state, so dedupe depends entirely on the `agent_seen` table — and if
`BUTTERBASE_API_KEY` is ever missing, a scheduled run would re-reply to every
thread in the window on every tick.

---

## 3. Docker

> **Status: written but never built.** Docker was not installed on the machine
> where this was authored, so the image is unverified. `pip install .` and the
> entrypoint import are verified. Build it before relying on it.

For the continuous poller — `managed_agent run` loops every 60 seconds, which
neither a Butterbase function (300s ceiling) nor an Actions job can host. Also
the right target when the host-side tools must run inside your own network.

```bash
docker build -t forgeflow .
docker run --rm --env-file .env forgeflow health   # verify credentials first
docker run -d --name forgeflow --env-file .env --restart unless-stopped forgeflow
```

The entrypoint is `python -m forgeflow.managed_agent`; the default command is
`run`. Override it for one-shot work:

```bash
docker run --rm --env-file .env forgeflow scan     # one thread, then exit
docker run --rm --env-file .env forgeflow health   # credential check, no work
```

Runs as UID 10001, not root. `.env` is excluded from the image by
`.dockerignore` — secrets come in at run time via `--env-file` or your
orchestrator's secret store, never baked into a layer.

**Do not run this alongside the Butterbase cron** unless `BUTTERBASE_API_KEY`
is set in the container. Both consult `agent_seen` for dedupe; without it the
container falls back to a local JSON file, the two schedulers stop seeing each
other's work, and suppliers get duplicate chases.

---

## Credentials

Every target needs the same set. Names are identical everywhere.

| Variable | Secret | What it is |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | runs the agent |
| `FORGEFLOW_OUTLOOK_REFRESH_TOKEN` | ✅ | mints Graph access tokens; **rotates on every use** |
| `FORGEFLOW_AZURE_CLIENT_ID` | ✅ | the app registration; must allow public client flows |
| `BUTTERBASE_API_KEY` | ✅ | comparison table + seen state |
| `FORGEFLOW_TRIGGER_KEY` | ✅ | gates `fn/trigger`; generated, not issued by anyone |
| `FORGEFLOW_AGENT_ID` | | coordinator agent |
| `FORGEFLOW_REPLY_AGENT_ID` | | reply subagent |
| `FORGEFLOW_ENV_ID` | | Anthropic environment |
| `BUTTERBASE_APP_URL` | | `https://api.butterbase.ai/v1/<app_id>` |
| `FORGEFLOW_MANAGED_AGENT_AUTOSEND` | | `true` to send for real; anything else drafts |

Locally these live in `.env` (gitignored). `forgeflow.config.load_env` uses
`setdefault`, so a real environment variable always wins over the file — which
is what makes the same code work unchanged in a container and on a runner.

### Recovering a dead Outlook token

Symptom: `Outlook 登录已失效` or `AADSTS70002` in the logs.

```bash
PYTHONPATH=src python3 -m forgeflow.cli login-outlook   # device code; complete it in a browser
PYTHONPATH=src python3 -m forgeflow.managed_agent health
python butterbase/set-secrets.py --apply
```

The device-code flow needs a human at a browser — it cannot be automated. If
`login-outlook` fails with `AADSTS70002`, the client ID in `.env` belongs to an
app registration that requires a client secret; use the one that has
**Allow public client flows = Yes**.

---

## Known constraints

- **`record_extraction` writes only when Butterbase is configured.** Without
  `BUTTERBASE_APP_URL` + `BUTTERBASE_API_KEY` it falls back to SQLite, which on
  any ephemeral host means the comparison table is empty on every run.
- **The dashboard shows a snapshot, not live data.** `fn/rfqs` is
  `auth: required` and the app has no end-user auth, so a browser cannot read
  it. `deploy-frontend.py` bakes the current table into the page — redeploy to
  refresh.
- **One RFQ per Outlook conversation.** `rfqs.id` is the `thread_id`, so two
  suppliers replying in separate conversations become two RFQ rows rather than
  one comparison. Suppliers must reply into the same thread to be compared.
- **Token rotation is not self-healing.** See *Token rotation* above.
