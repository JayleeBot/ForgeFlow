"""Deploy butterbase/functions/*.ts.

    python butterbase/deploy-functions.py

scan.ts is deployed twice from one source:

  scan     cron every 10 minutes, HTTP trigger auth:required
  trigger  HTTP auth:none at the platform, but the handler itself demands
           x-forgeflow-key and fails closed when FORGEFLOW_TRIGGER_KEY is unset

Two deployments rather than two files so the scan logic has one definition; the
handler tells them apart by its own request path.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forgeflow.config import load_env

FUNCTIONS = Path(__file__).resolve().parent / "functions"

# name -> triggers
PLAN = {
    "rfqs": [{"type": "http", "config": {"auth": "required"}}],
    "scan": [
        {"type": "cron", "config": {"schedule": "*/10 * * * *"}},
        {"type": "http", "config": {"auth": "required"}},
    ],
    # Gated inside the handler, not by the platform -- see scan.ts.
    "trigger": [{"type": "http", "config": {"auth": "none"}}],
}
SOURCE = {"rfqs": "rfqs.ts", "scan": "scan.ts", "trigger": "scan.ts"}


def call(api: str, path: str, payload=None, method="POST"):
    headers = {"Authorization": f"Bearer {os.environ['BUTTERBASE_API_KEY']}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        api + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            # Not truncated: callers parse this as JSON.
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def main() -> None:
    load_env()
    api = os.environ["BUTTERBASE_APP_URL"].rstrip("/")
    for name, triggers in PLAN.items():
        code = (FUNCTIONS / SOURCE[name]).read_text()
        if name == "trigger":
            # Flip the compile-time marker rather than sniffing request.url,
            # which never matched and left the endpoint ungated.
            code = code.replace("const IS_TRIGGER = false;", "const IS_TRIGGER = true;", 1)
            if "const IS_TRIGGER = true;" not in code:
                raise SystemExit("IS_TRIGGER marker missing from scan.ts")
        payload = {"name": name, "code": code, "triggers": triggers}
        if name != "rfqs":
            # A scan runs one opus session; 30s is not enough.
            payload["timeout"] = 300
        status, body = call(api, "/functions", payload)
        summary = [t["type"] for t in triggers]
        print(f"{name:8} {status} {summary}")
        if status >= 400:
            print(f"         {body[:300]}")

    status, body = call(api, "/functions", method="GET")
    for f in json.loads(body).get("functions", []) if status < 400 else []:
        print(f"  live: {f['name']:8} {[(t['type'], t.get('config')) for t in f['triggers']]}")


if __name__ == "__main__":
    main()
