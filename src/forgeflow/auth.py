from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from forgeflow.config import set_env_values


AUTH_ROOT = "https://login.microsoftonline.com"
# Mail.Send is what /messages/{id}/reply needs — without it the agent can read a
# thread and draft a reply but never send one.
DEFAULT_SCOPES = "offline_access User.Read Mail.Read Mail.Send"


def _with_client_auth(body: dict[str, str]) -> dict[str, str]:
    """Add client_secret when the app registration is a confidential client.

    A public client (Authentication -> "Allow public client flows" = Yes) must
    NOT send one; a confidential client must, and rejects the request with
    AADSTS70002 otherwise. Reading it from the environment lets one code path
    serve both, since which kind the app is is a portal setting we cannot see.
    """
    secret = os.environ.get("FORGEFLOW_AZURE_CLIENT_SECRET")
    if secret:
        body = {**body, "client_secret": secret}
    return body


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
                _with_client_auth({
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device["device_code"],
                }),
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
            "FORGEFLOW_AZURE_CLIENT_ID": client_id,
            "FORGEFLOW_AZURE_TENANT_ID": tenant,
        }
        if token.get("refresh_token"):
            values["FORGEFLOW_OUTLOOK_REFRESH_TOKEN"] = token["refresh_token"]
        set_env_values(values)
        print("Saved delegated Outlook token to .env", flush=True)
        return
    raise TimeoutError("Device login expired before authentication completed")


RELOGIN_HINT = "Outlook 登录已失效,请重新运行: forgeflow login-outlook"


def refresh_access_token(
    client_id: str | None = None,
    tenant: str | None = None,
    refresh_token: str | None = None,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    client_id = client_id or os.environ.get("FORGEFLOW_AZURE_CLIENT_ID")
    tenant = tenant or os.environ.get("FORGEFLOW_AZURE_TENANT_ID") or "consumers"
    refresh_token = refresh_token or os.environ.get("FORGEFLOW_OUTLOOK_REFRESH_TOKEN")
    if not client_id or not refresh_token:
        raise RuntimeError(RELOGIN_HINT)
    try:
        token = _post(
            f"{AUTH_ROOT}/{tenant}/oauth2/v2.0/token",
            _with_client_auth({
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": scopes,
            }),
        )
    except RuntimeError as exc:
        raise RuntimeError(RELOGIN_HINT) from exc

    values = {"FORGEFLOW_OUTLOOK_ACCESS_TOKEN": token["access_token"]}
    if token.get("refresh_token"):
        values["FORGEFLOW_OUTLOOK_REFRESH_TOKEN"] = token["refresh_token"]
    set_env_values(values)
    return token["access_token"]


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
