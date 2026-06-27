from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from forgeflow.config import set_env_values


AUTH_ROOT = "https://login.microsoftonline.com"
DEFAULT_SCOPES = "offline_access User.Read Mail.Read"


def device_login(client_id: str, tenant: str = "consumers", scopes: str = DEFAULT_SCOPES) -> None:
    device = _post(
        f"{AUTH_ROOT}/{tenant}/oauth2/v2.0/devicecode",
        {"client_id": client_id, "scope": scopes},
    )
    print(device["message"], flush=True)

    token_url = f"{AUTH_ROOT}/{tenant}/oauth2/v2.0/token"
    deadline = time.time() + int(device["expires_in"])
    interval = int(device.get("interval", 5))
    while time.time() < deadline:
        time.sleep(interval)
        try:
            token = _post(
                token_url,
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device["device_code"],
                },
            )
        except RuntimeError as exc:
            message = str(exc)
            if "authorization_pending" in message:
                continue
            if "slow_down" in message:
                interval += 5
                continue
            raise

        values = {
            "FORGEFLOW_OUTLOOK_ACCESS_TOKEN": token["access_token"],
            "FORGEFLOW_OUTLOOK_AUTH_MODE": "delegated",
            "FORGEFLOW_OUTLOOK_MAILBOX": "me",
        }
        if token.get("refresh_token"):
            values["FORGEFLOW_OUTLOOK_REFRESH_TOKEN"] = token["refresh_token"]
        set_env_values(values)
        print("Saved delegated Outlook token to .env", flush=True)
        return
    raise TimeoutError("Device login expired before authentication completed")


def _post(url: str, data: dict[str, str]) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(body or f"HTTP {exc.code}") from exc
