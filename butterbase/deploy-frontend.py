"""Build butterbase/dashboard/ and deploy it to the app's live URL.

    python butterbase/deploy-frontend.py                  build + deploy
    python butterbase/deploy-frontend.py --snapshot-only   dev data, no deploy
    python butterbase/deploy-frontend.py --demo            public demo: sample data only

`npm run build` produces dashboard/dist/, which is what gets zipped. Then three
steps, all against api.butterbase.ai:

  POST /v1/{app}/frontend/deployments   -> {id, uploadUrl}   (presigned R2, 15 min)
  PUT  {uploadUrl}                       -> the zip
  POST /v1/{app}/frontend/deployments/{id}/start

The zip must have index.html at its ROOT with POSIX separators, or the platform
serves every file as text/html and the page comes up blank. zipfile writes
forward slashes on every OS, so building it here rather than shelling out to a
system zip tool avoids that class of bug entirely.

`--snapshot-only` writes the same data to dashboard/public/snapshot.json, which
`npm run dev` serves and the page falls back to when nothing was baked in. It is
gitignored: it holds real supplier quotes.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forgeflow.config import load_env

APP = Path(__file__).resolve().parent / "dashboard"
SRC = APP / "dist"
BASE = "https://api.butterbase.ai"


def call(url: str, payload=None, method="POST", raw: bytes | None = None,
         content_type: str | None = None):
    headers = {}
    if not url.startswith(BASE):
        pass  # presigned URL: must be sent WITHOUT our Authorization header
    else:
        headers["Authorization"] = f"Bearer {os.environ['BUTTERBASE_API_KEY']}"
    body = raw
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            text = r.read().decode(errors="replace")
            return r.status, (json.loads(text) if text.strip().startswith(("{", "[")) else text)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def snapshot_payload() -> dict:
    """The current comparison table, as the dashboard wants to read it.

    The read function is auth:required and the app has no end-user auth, so a
    browser cannot fetch it. This script holds the service key, so it can read
    the table here and ship the result as data -- no public endpoint, and no
    credential in the bundle. The cost is that it is a snapshot: redeploy to
    refresh.
    """
    from datetime import datetime, timezone

    from forgeflow import butterbase

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rfqs": butterbase.dashboard_payload() if butterbase.enabled() else [],
        "trigger_url": f"{os.environ.get('BUTTERBASE_APP_URL', '').rstrip('/')}/fn/trigger",
    }


def snapshot_script() -> str:
    blob = json.dumps(snapshot_payload(), default=str).replace("</", "<\\/")
    return f"<script>window.__FORGEFLOW_SNAPSHOT__ = {blob};</script>\n"


def npm_build(demo: bool) -> None:
    script = "build:demo" if demo else "build"
    print(f"building {APP.name}/ ({script}) …")
    subprocess.run(["npm", "run", script], cwd=APP, check=True)


def build_zip(demo: bool) -> bytes:
    # The demo carries its own invented data. Reading the real tables here, even
    # to discard them, would be one bug away from publishing supplier quotes.
    script = "" if demo else snapshot_script()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(SRC.rglob("*")):
            if not path.is_file():
                continue
            if path.name == "snapshot.json":
                # Vite copies public/ into dist/, but the dev snapshot has no
                # business being served: the data is baked into the page below,
                # and a public JSON of supplier quotes is not something to ship.
                continue
            data = path.read_bytes()
            if path.name == "index.html" and script:
                # First thing in the head, so window.__FORGEFLOW_SNAPSHOT__ is
                # set before anything reads it.
                data = data.decode().replace("<head>", "<head>\n" + script, 1).encode()
            # arcname relative to SRC -> index.html lands at the zip root
            z.writestr(path.relative_to(SRC).as_posix(), data)
    return buf.getvalue()


def main() -> None:
    load_env()

    if "--snapshot-only" in sys.argv:
        out = APP / "public" / "snapshot.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot_payload(), default=str, indent=2))
        print(f"wrote {out} ({out.stat().st_size:,} bytes) — `npm run dev` will serve it")
        return

    app_id = os.environ.get("BUTTERBASE_APP_ID") or \
        os.environ["BUTTERBASE_APP_URL"].rstrip("/").rsplit("/", 1)[-1]
    api = f"{BASE}/v1/{app_id}"

    demo = "--demo" in sys.argv
    npm_build(demo)
    if not (SRC / "index.html").exists():
        raise SystemExit(f"No index.html in {SRC}")
    blob = build_zip(demo)
    print(f"zip: {len(blob):,} bytes, {len(zipfile.ZipFile(io.BytesIO(blob)).namelist())} file(s)")

    code, body = call(f"{api}/frontend/deployments", {"app_id": app_id, "framework": "static"})
    if code >= 400:
        raise SystemExit(f"create deployment failed: {code} {body}")
    deployment_id, upload_url = body["id"], body["uploadUrl"]
    print(f"deployment: {deployment_id}")

    code, body = call(upload_url, raw=blob, method="PUT", content_type="application/zip")
    if code >= 400:
        raise SystemExit(f"upload failed: {code} {body}")
    print(f"uploaded: {code}")

    code, body = call(f"{api}/frontend/deployments/{deployment_id}/start")
    print(f"start: {code} {str(body)[:200]}")
    if code >= 400:
        raise SystemExit("start failed")

    for _ in range(30):
        code, body = call(f"{api}/frontend/deployments/{deployment_id}", method="GET")
        status = body.get("status") if isinstance(body, dict) else body
        print(f"  status={status}")
        if status in ("READY", "FAILED", "ERROR"):
            if isinstance(body, dict) and body.get("url"):
                print(f"\nLive: {body['url']}")
            if isinstance(body, dict) and body.get("error"):
                print(f"error: {body['error']}")
            return
        time.sleep(10)
    print("still building after 5 minutes")


if __name__ == "__main__":
    main()
