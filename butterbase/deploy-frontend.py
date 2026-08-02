"""Deploy butterbase/frontend/ to the app's live URL.

    python butterbase/deploy-frontend.py

Three steps, all against api.butterbase.ai:

  POST /v1/{app}/frontend/deployments   -> {id, uploadUrl}   (presigned R2, 15 min)
  PUT  {uploadUrl}                       -> the zip
  POST /v1/{app}/frontend/deployments/{id}/start

The zip must have index.html at its ROOT with POSIX separators, or the platform
serves every file as text/html and the page comes up blank. zipfile writes
forward slashes on every OS, so building it here rather than shelling out to a
system zip tool avoids that class of bug entirely.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forgeflow.config import load_env

SRC = Path(__file__).resolve().parent / "frontend"
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


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(SRC.rglob("*")):
            if path.is_file():
                # arcname relative to SRC -> index.html lands at the zip root
                z.write(path, path.relative_to(SRC).as_posix())
    return buf.getvalue()


def main() -> None:
    load_env()
    app_id = os.environ.get("BUTTERBASE_APP_ID") or \
        os.environ["BUTTERBASE_APP_URL"].rstrip("/").rsplit("/", 1)[-1]
    api = f"{BASE}/v1/{app_id}"

    if not (SRC / "index.html").exists():
        raise SystemExit(f"No index.html in {SRC}")
    blob = build_zip()
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
