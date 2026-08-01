"""Copy the two runtime secrets from .env into the Butterbase app environment.

Run this yourself -- it reads your .env and writes to Butterbase's env store, so
the values never pass through anything else. The non-secret identifiers
(FORGEFLOW_AGENT_ID, FORGEFLOW_ENV_ID, FORGEFLOW_OUTLOOK_TOP) are already set.

    python butterbase/set-secrets.py            # show what would be sent, by name
    python butterbase/set-secrets.py --apply    # write them

Add FORGEFLOW_MANAGED_AGENT_AUTOSEND=true to .env first only if you want the
cron to send replies for real. Leave it out and the agent drafts to the function
log instead -- worth doing for one cycle before letting it email suppliers.
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

# Secrets the function needs at runtime. Anything non-secret is already in place.
WANTED = [
    "ANTHROPIC_API_KEY",
    "FORGEFLOW_OUTLOOK_REFRESH_TOKEN",
    "FORGEFLOW_AZURE_CLIENT_ID",
    "FORGEFLOW_AZURE_TENANT_ID",
    "FORGEFLOW_MANAGED_AGENT_AUTOSEND",
]


def main() -> None:
    load_env()
    api_key = os.environ.get("BUTTERBASE_API_KEY")
    app_url = (os.environ.get("BUTTERBASE_APP_URL") or "").rstrip("/")
    if not api_key or not app_url:
        raise SystemExit("BUTTERBASE_API_KEY and BUTTERBASE_APP_URL must be in .env")

    env_vars = {k: os.environ[k] for k in WANTED if os.environ.get(k)}
    missing = [k for k in WANTED[:3] if k not in env_vars]
    if missing:
        raise SystemExit(f"Not in .env, so nothing to copy: {', '.join(missing)}")

    print("Would set (values not shown):")
    for key in env_vars:
        print(f"  {key}  ({len(env_vars[key])} chars)")
    if "FORGEFLOW_MANAGED_AGENT_AUTOSEND" not in env_vars:
        print("\n  FORGEFLOW_MANAGED_AGENT_AUTOSEND is unset -> the agent will draft, not send.")

    if "--apply" not in sys.argv:
        print("\nDry run. Re-run with --apply to write them.")
        return

    request = urllib.request.Request(
        f"{app_url}/env",
        data=json.dumps({"envVars": env_vars}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print("\n" + json.dumps(json.loads(response.read().decode()), indent=2))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:400]}")


if __name__ == "__main__":
    main()
