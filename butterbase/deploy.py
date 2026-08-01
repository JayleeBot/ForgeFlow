"""Apply butterbase/schema.json to a Butterbase app.

Credentials come from the environment, never from a file or an argument, so the
key stays out of the repo and out of shell history:

    export BUTTERBASE_API_KEY=bb_sk_...
    export BUTTERBASE_APP_URL=https://<app_id>.butterbase.ai

    python butterbase/deploy.py            # dry run -- prints the diff, changes nothing
    python butterbase/deploy.py --apply    # applies it

Butterbase diffs the desired state against the live database and applies only
what differs, so re-running after an edit is the normal way to migrate.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.json"


def main() -> None:
    api_key = os.environ.get("BUTTERBASE_API_KEY")
    app_url = (os.environ.get("BUTTERBASE_APP_URL") or "").rstrip("/")
    if not api_key or not app_url:
        raise SystemExit(
            "Set BUTTERBASE_API_KEY and BUTTERBASE_APP_URL first. The app URL is the\n"
            "per-app subdomain shown in the Butterbase dashboard."
        )

    payload = json.loads(SCHEMA_PATH.read_text())
    payload["dry_run"] = "--apply" not in sys.argv

    mode = "DRY RUN" if payload["dry_run"] else "APPLY"
    tables = ", ".join(sorted(payload["schema"]["tables"]))
    print(f"[{mode}] {app_url}/schema/apply")
    print(f"  tables: {tables}\n")

    request = urllib.request.Request(
        f"{app_url}/schema/apply",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise SystemExit(f"HTTP {exc.code}: {body or 'no body'}") from exc

    if payload["dry_run"]:
        print("\nNothing was changed. Re-run with --apply to commit it.")


if __name__ == "__main__":
    main()
