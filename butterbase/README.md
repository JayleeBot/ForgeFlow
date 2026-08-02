# Working with Butterbase

Field notes for this app. Written from what the API actually does, which differs
from the published docs in several places — each difference below cost a round
trip to discover, so check here before trusting docs.butterbase.ai.

App: `app_nkpie8ug8oun` · API `https://api.butterbase.ai/v1/app_nkpie8ug8oun` ·
site `https://forgeflow-rfq.butterbase.dev`

## Layout

```
butterbase/
  schema.json           declarative schema (source of truth for the tables)
  deploy.py             apply schema.json          (dry run unless --apply)
  deploy-functions.py   deploy functions/*.ts
  deploy-frontend.py    zip + upload + start frontend/, baking in a data snapshot
  set-secrets.py        copy runtime secrets from .env into the app env
  push-rotated-token.py CI-only: hand the rotated Outlook token to Butterbase
  functions/*.ts        server-side functions
  frontend/index.html   the dashboard
```

Credentials always come from `.env` via `forgeflow.config.load_env` — nothing is
committed, and no value is ever printed.

## Auth model

| Caller | Role | Notes |
|---|---|---|
| no header | `butterbase_anon` | this app has **no** end-user auth; anonymous is refused |
| `bb_sk_…` | `butterbase_service` | full access, bypasses RLS. **Server-side only.** |
| end-user JWT | `butterbase_user` | not available here — every `/auth/*` route 404s |

There is no magic-link or OAuth on this app. `/auth/magiclink`, `/auth/otp`,
`/auth/login`, `/auth/token`, `/auth/verify` all return "Route not found". Any
design that assumes a browser can obtain a token is currently unbuildable.

**Never ship `bb_sk_` to a browser.** The dashboard works around this by baking
a data snapshot in at deploy time (see `deploy-frontend.py`).

## Schema

Declarative JSON: describe desired state, the platform diffs and applies. See
`schema.json`, apply with `deploy.py` (dry run by default).

```
POST /v1/{app}/schema/apply    {name, dry_run, schema: {tables: {...}}}
GET  /v1/{app}/schema
```

Gotchas, all discovered by 400s:

- Primary keys are **`primaryKey`**, not `primary` as documented.
- Do **not** put `nullable: false` beside `primaryKey`. Postgres already implies
  NOT NULL there, so the diff engine emits the same `ALTER` forever and the
  schema never converges. `applied: 0` on a re-run is what correct looks like.
- Composite keys aren't expressible per-column — use a single `id` plus a
  `unique` index over the columns.
- Column types are Postgres names: `text`, `jsonb`, `timestamptz`,
  `numeric(12,4)`, `uuid`, `boolean`, `integer`.
- The format covers tables and indexes only. No views, no RLS policies.

## Data API

PostgREST-flavoured, at `/v1/{app}/{table}`.

```
GET    /v1/{app}/rfqs?order=updated_at.desc&limit=25&select=id,subject
GET    /v1/{app}/supplier_quotes?rfq_id=eq.THREAD_ID
POST   /v1/{app}/{table}          insert
PATCH  /v1/{app}/{table}/{id}     update
DELETE /v1/{app}/{table}/{id}
```

Filter operators: `eq neq gt gte lt lte like ilike is in fts`.

- **No upsert.** `forgeflow/butterbase.py` fakes it with deterministic ids and
  PATCH-then-POST. Inside a function, prefer real SQL `ON CONFLICT`.
- **A bare JSON array is rejected for a `jsonb` column** — Postgres tries to
  parse it as an object and fails with `22P02`. Wrap lists (`{"items": [...]}`)
  and unwrap on read; `butterbase.py` does this symmetrically.
- **Do not send `Content-Type: application/json` without a body.** The API
  rejects it, which silently breaks every DELETE. Set the header only when
  there is a payload.
- Any unknown path under `/v1/{app}/` is treated as a **table name**, so a typo
  returns `VALIDATION_TABLE_NOT_FOUND` rather than a 404. "Table X not found"
  usually means "that route doesn't exist".

## Functions

```
GET  /v1/{app}/functions
POST /v1/{app}/functions        {name, code, triggers|trigger, timeout}
GET  /v1/{app}/functions/{name}/logs
POST /v1/{app}/functions/{name} … (re-POST the same name to redeploy)
DELETE /v1/{app}/functions/{name}
ANY  /v1/{app}/fn/{name}        invoke
```

- Must `export async function handler(request, context)`. A default export or an
  arrow function is rejected with "Function must export a handler function".
- `npm:` specifiers work — `import Anthropic from "npm:@anthropic-ai/sdk"`.
- Outbound HTTPS works (Microsoft Graph, login.microsoftonline.com).
- `context.db.query(sql, params)` gives real SQL. `context.env` holds app env.
- **Default timeout is 30s, max 300s — set `timeoutMs`, in milliseconds.**
  `timeout: 300` is accepted and silently ignored, and the function then dies at
  exactly 30000ms with `function_timeout`. Use `"timeoutMs": 300000` for
  anything that runs a model call. `GET /functions/{name}` echoes the effective
  `timeoutMs` and `memoryLimitMb`, which is the way to confirm it took.
- Trigger auth is `{"type": "http", "config": {"auth": "none" | "required"}}`.
  With `required`, **not even the service key works** — it wants an end-user
  JWT, which this app cannot issue. So `required` means "cron only" in practice.
- Cron: `{"type": "cron", "config": {"schedule": "*/10 * * * *"}}`. Cron fires
  regardless of the HTTP trigger's auth setting.
- `/logs` is the only way to see errors; the invoke response may be opaque.

### The TS SDK differs from Python

Two shapes that the Python port got wrong:

```ts
const stream = await client.beta.sessions.events.stream(session.id);  // positional, and awaited
await client.beta.sessions.events.send(session.id, { events: [...] });
```

Passing `{session_id}` gives "path parameters result in path with invalid
segments". Not awaiting `stream()` gives "stream is not async iterable".

### Gating a function without platform auth

`scan.ts` is deployed twice from one source: as `scan` (cron, HTTP
`auth: required`) and as `trigger` (HTTP `auth: none`, but the handler checks
`x-forgeflow-key` against `FORGEFLOW_TRIGGER_KEY` and **fails closed** when that
is unset). `deploy-functions.py` flips a compile-time `IS_TRIGGER` constant.

Do not try to detect this from `request.url` — an earlier version tested
`pathname.endsWith("/trigger")`, which never matched, leaving the endpoint
running full unauthenticated scans.

**The key travels in a `text/plain` body, not a custom header.** A custom
request header (`x-forgeflow-key`) forces a CORS preflight, and this API does
not echo that header on the `OPTIONS` response, so the browser blocks the call
before it is sent — it surfaces only as `TypeError: Failed to fetch`, with no
server-side trace at all. `text/plain` is CORS-safelisted, so a POST carrying
the key as its body is a simple request and goes straight through. Plain `GET`s
are simple too, which is why cross-origin reads worked while the trigger did
not. The handler accepts either form; only the browser needs the body variant.

## App environment

```
GET   /v1/{app}/env                    names only, never values
PATCH /v1/{app}/env   {"envVars": {...}}
```

`POST`/`PUT` do not exist — `POST /env` falls through to the table handler.
Changing env invalidates and redeploys every function.

Use `set-secrets.py` (dry run by default) rather than hand-rolling this.

## Frontend deploy

```
POST /v1/{app}/frontend/deployments        {app_id, framework}  -> {id, uploadUrl}
PUT  {uploadUrl}                            the zip, Content-Type: application/zip
POST /v1/{app}/frontend/deployments/{id}/start
GET  /v1/{app}/frontend/deployments/{id}    poll until status READY
```

Frameworks: `static`, `react-vite` (`dist/`), `nextjs-static` (`out/`; needs
`output: 'export'` in `next.config.js`).

- The route lives under `/v1/{app}/`, alongside the data API — not `/frontend`,
  `/deploy` or `/apps/{app}/...`.
- **`index.html` must be at the zip ROOT with POSIX separators.** Nesting it, or
  zipping with a Windows tool that writes backslashes, gives a blank page or
  MIME errors. `deploy-frontend.py` uses Python `zipfile`, which always writes
  forward slashes.
- **Send the presigned PUT without the Authorization header** — the URL carries
  its own signature. It expires in 15 minutes.
- Free plan allows 1 deployment per app; deploying again replaces it.
- CORS lives in `allowed_origins` on the app config, which is **read-only over
  the API** (`GET /v1/{app}/config`). Change it in the dashboard UI.

## Discovery method

The docs are approximate; the API is authoritative and its errors are good.
When a route is unknown, POST a plausible payload and read the reply:

- `Route POST:/v1/... not found` → no such route.
- `VALIDATION_TABLE_NOT_FOUND` → not a route either; it fell through to the
  Data API. Try a different path prefix.
- A validation error naming your fields → the route exists; fix the payload.

`GET /v1/{app}/functions` echoes each trigger's full config, which is how the
`auth` key was found. The skills repo `butterbase-ai/butterbase-skills`
documents workflows the API reference omits — `skills/deploy-frontend/SKILL.md`
is where the deployment sequence above came from.

## Known gaps

- No end-user auth, so the dashboard cannot read live data from a browser. It
  ships a deploy-time snapshot instead; redeploy to refresh.
- No RLS policies. Tables have no owner column, so adding them means a schema
  change first.
- `scan.ts` refreshes the Outlook access token but does not persist the rotated
  *refresh* token back to the app env. Butterbase's stored credential therefore
  ages, and today it is a GitHub Actions run (`push-rotated-token.py`) that
  refreshes it. Until the function does this itself, do not retire that workflow.
