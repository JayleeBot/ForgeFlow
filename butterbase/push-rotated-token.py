"""Push the rotated Outlook refresh token from a CI runner into Butterbase.

Entra issues a new refresh token on every redemption. refresh_access_token
writes it to .env, and on a runner that file dies with the job -- so the stored
credential drifts stale and eventually stops working. This hands it to
Butterbase instead, server to server, so the function's token is refreshed by
every workflow run.

Reads .env DIRECTLY rather than through load_env(): load_env uses setdefault, so
the job's own environment variable would win and we would push back the same
stale token we started with.

Not a general secret-copier -- it moves exactly one value, and only forward.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

KEY = "FORGEFLOW_OUTLOOK_REFRESH_TOKEN"


def token_from_env_file(path: Path = Path(".env")) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == KEY:
            return value.strip().strip('"').strip("'") or None
    return None


def main() -> None:
    api_key = os.environ.get("BUTTERBASE_API_KEY")
    app_url = (os.environ.get("BUTTERBASE_APP_URL") or "").rstrip("/")
    if not api_key or not app_url:
        print("Butterbase not configured; nothing to push.")
        return

    rotated = token_from_env_file()
    if not rotated:
        print("No rotated token was written this run; nothing to push.")
        return
    if rotated == os.environ.get(KEY):
        print("Token did not rotate this run; nothing to push.")
        return

    request = urllib.request.Request(
        f"{app_url}/env",
        data=json.dumps({"envVars": {KEY: rotated}}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode())
        print(f"Pushed rotated token ({len(rotated)} chars) -> {body.get('updatedKeys')}")
    except urllib.error.HTTPError as exc:
        # Never fatal: the scan itself already succeeded by this point.
        print(f"Could not push rotated token: HTTP {exc.code} "
              f"{exc.read().decode('utf-8', 'replace')[:200]}", file=sys.stderr)


if __name__ == "__main__":
    main()
