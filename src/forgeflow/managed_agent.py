"""Run ForgeFlow's RFQ triage as a Claude Managed Agent — coordinator + subagent.

Shape:

    Coordinator (ForgeFlow RFQ Coordinator)
      ├─ read_comparison_table   host-side: what we already have for this RFQ
      ├─ record_extraction       host-side: writes this supplier's state into the table
      └─ delegates to ──► Reply agent (subagent, its own thread)
                            └─ send_reply   host-side: Microsoft Graph

Anthropic hosts the agent loop and the subagent threads. ForgeFlow keeps the mailbox and
the comparison table: every tool that touches either runs in THIS process, so the Outlook
token and the database never enter the sandbox. Subagent tool calls are cross-posted to
the primary thread, so one event stream drives everything.

    python -m forgeflow.managed_agent setup     # one-time: environment + both agents
    python -m forgeflow.managed_agent deploy    # push prompt/tool changes to both
    python -m forgeflow.managed_agent health
    python -m forgeflow.managed_agent test [message_id]
    python -m forgeflow.managed_agent scan      # one pass over the inbox, then exit
    python -m forgeflow.managed_agent run       # poll the inbox
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic

from forgeflow import butterbase
from forgeflow.auth import refresh_access_token
from forgeflow.config import load_env, set_env_values
from forgeflow.graph import GraphMailbox
from forgeflow.models import EmailMessage
from forgeflow.store import connect, rfq_states

MODEL = {"id": "claude-opus-5", "effort": "xhigh"}
SEEN_PATH = Path("data/managed_agent_seen.json")
POLL_INTERVAL_SECONDS = 60
_PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")


# ── Host-side tools ───────────────────────────────────────────────────────────

READ_TABLE_TOOL = {
    "type": "custom",
    "name": "read_comparison_table",
    "description": (
        "Return the quotes collected so far for an RFQ, across every supplier and every "
        "earlier round. Call this before deciding what is outstanding — a field answered "
        "in an earlier round is already answered."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rfq_reference": {
                "type": "string",
                "description": "The RFQ reference or thread subject to look up. Pass the "
                               "buyer's reference when the thread states one.",
            },
        },
        "required": ["rfq_reference"],
    },
}

RECORD_TOOL = {
    "type": "custom",
    "name": "record_extraction",
    "description": (
        "Write this supplier's current state into the comparison table. Send the complete "
        "picture for this supplier, not only what the newest email added."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "supplier_name": {"type": "string"},
            "classification": {
                "type": "string",
                "enum": ["rfq_sent", "supplier_quote", "supplier_reminder", "ignore"],
            },
            "extraction": {
                "type": "object",
                "description": "The collection form and this supplier's quote, as extracted.",
            },
        },
        "required": ["supplier_name", "classification", "extraction"],
    },
}

SEND_REPLY_TOOL = {
    "type": "custom",
    "name": "send_reply",
    "description": (
        "Reply to a message in the email thread. Give the message_id being replied to and "
        "the body text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "The message_id being replied to."},
            "body_text": {"type": "string", "description": "The reply body to send."},
        },
        "required": ["message_id", "body_text"],
    },
}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


# ── Provisioning ──────────────────────────────────────────────────────────────

def _reply_agent_config() -> dict:
    return {
        "name": "ForgeFlow Reply Agent",
        "model": MODEL,
        "system": _prompt("reply_agent.txt"),
        "tools": [SEND_REPLY_TOOL],
    }


def _coordinator_config(reply_agent_id: str) -> dict:
    """Typed args for agents.create/update.

    `multiagent` is not a typed parameter in anthropic 0.96.0, so it rides in
    extra_body — see _multiagent_body(). Drop that once the SDK types it.
    """
    return {
        "name": "ForgeFlow RFQ Coordinator",
        "model": MODEL,
        "system": _prompt("coordinator.txt"),
        "tools": [READ_TABLE_TOOL, RECORD_TOOL],
    }


def _multiagent_body(reply_agent_id: str) -> dict:
    return {"extra_body": {"multiagent": {"type": "coordinator", "agents": [reply_agent_id]}}}


def _roster(agent) -> list:
    """The subagent roster, read defensively — `multiagent` is untyped in this SDK."""
    ma = getattr(agent, "multiagent", None)
    if ma is None and hasattr(agent, "model_extra"):
        ma = (agent.model_extra or {}).get("multiagent")
    if ma is None:
        return []
    agents = getattr(ma, "agents", None) if not isinstance(ma, dict) else ma.get("agents")
    return list(agents or [])


def _reachable(fetch, resource_id: str | None):
    """An ID in .env is only useful if the current API key can actually see it.

    Agents and environments are workspace-scoped, so switching keys silently
    orphans every ID from the previous workspace.
    """
    if not resource_id:
        return None
    try:
        return fetch(resource_id)
    except anthropic.NotFoundError:
        print(f"  {resource_id} is not visible to this API key — provisioning a replacement.")
        return None


def setup() -> None:
    """Create the environment and both agents; persist their IDs to .env."""
    client = _client()

    env_id = os.environ.get("FORGEFLOW_ENV_ID")
    if not _reachable(lambda i: client.beta.environments.retrieve(i), env_id):
        env_id = client.beta.environments.create(
            name="forgeflow-rfq",
            config={"type": "cloud", "networking": {"type": "unrestricted"}},
        ).id
        print(f"Created environment {env_id}")

    reply_id = os.environ.get("FORGEFLOW_REPLY_AGENT_ID")
    if _reachable(lambda i: client.beta.agents.retrieve(i), reply_id):
        print(f"Reusing reply subagent {reply_id}")
    else:
        reply = client.beta.agents.create(**_reply_agent_config())
        reply_id = reply.id
        print(f"Created reply subagent {reply_id} (v{reply.version})")

    coordinator_id = os.environ.get("FORGEFLOW_AGENT_ID")
    current = _reachable(lambda i: client.beta.agents.retrieve(i), coordinator_id)
    if current:
        coordinator = client.beta.agents.update(
            coordinator_id, version=current.version,
            **_coordinator_config(reply_id), **_multiagent_body(reply_id)
        )
        print(f"Promoted {coordinator.id} to coordinator (v{coordinator.version})")
    else:
        coordinator = client.beta.agents.create(
            **_coordinator_config(reply_id), **_multiagent_body(reply_id)
        )
        print(f"Created coordinator {coordinator.id} (v{coordinator.version})")

    set_env_values({
        "FORGEFLOW_AGENT_ID": coordinator.id,
        "FORGEFLOW_REPLY_AGENT_ID": reply_id,
        "FORGEFLOW_ENV_ID": env_id,
    })
    print("Saved FORGEFLOW_AGENT_ID / FORGEFLOW_REPLY_AGENT_ID / FORGEFLOW_ENV_ID to .env.")


def deploy() -> None:
    """Push the prompts and tool definitions in this repo to both live agents."""
    client = _client()
    coordinator_id = os.environ.get("FORGEFLOW_AGENT_ID")
    reply_id = os.environ.get("FORGEFLOW_REPLY_AGENT_ID")
    if not coordinator_id or not reply_id:
        raise SystemExit("Run `setup` first — both agent IDs must be in .env.")

    reply_current = client.beta.agents.retrieve(reply_id)
    reply = client.beta.agents.update(
        reply_id, version=reply_current.version, **_reply_agent_config()
    )
    print(f"Reply subagent {reply.id}: v{reply_current.version} -> v{reply.version}")

    coord_current = client.beta.agents.retrieve(coordinator_id)
    coordinator = client.beta.agents.update(
        coordinator_id, version=coord_current.version,
        **_coordinator_config(reply_id), **_multiagent_body(reply_id)
    )
    print(f"Coordinator {coordinator.id}: v{coord_current.version} -> v{coordinator.version}")
    print(f"  roster: {_roster(coordinator)}")


# ── Host-side tool execution ──────────────────────────────────────────────────

def _autosend() -> bool:
    return os.environ.get("FORGEFLOW_MANAGED_AGENT_AUTOSEND", "").lower() in ("1", "true", "yes")


def _run_read_table(tool_input: dict) -> str:
    reference = (tool_input.get("rfq_reference") or "").strip().lower()
    if butterbase.enabled():
        states = butterbase.rfq_states()
    else:
        with connect() as conn:
            states = rfq_states(conn)
    if reference:
        matched = [s for s in states
                   if reference in (s.get("subject") or "").lower()
                   or reference in (s.get("id") or "").lower()]
        states = matched or states
    if not states:
        return "The comparison table is empty — nothing has been collected for this RFQ yet."
    return json.dumps(states[:5], indent=2, default=str)


def _run_record(tool_input: dict) -> str:
    supplier = tool_input.get("supplier_name") or "unknown supplier"
    RECORDED.append(tool_input)
    if not butterbase.enabled() or not CURRENT_THREAD:
        return f"Recorded {supplier} into the comparison table."

    classification = tool_input.get("classification") or "unknown"
    extraction = tool_input.get("extraction")
    try:
        rfq_id = butterbase.upsert_rfq(
            CURRENT_THREAD["thread_id"],
            CURRENT_THREAD["subject"],
            CURRENT_THREAD.get("buyer_email"),
            classification,
            # On an rfq_sent thread the extraction *is* the collection form.
            collection_form=extraction if classification == "rfq_sent" else None,
        )
        if classification in ("supplier_quote", "supplier_reminder"):
            butterbase.upsert_supplier_quote(
                rfq_id,
                CURRENT_THREAD["thread_id"],
                CURRENT_THREAD["sender"],
                tool_input.get("supplier_name"),
                classification,
                extraction,
                CURRENT_THREAD["latest_message_id"],
            )
    except RuntimeError as exc:
        # Tell the agent the truth. The old version always claimed success,
        # so the coordinator trusted a table that was never written.
        return f"Could not write {supplier} to the comparison table: {exc}"
    return f"Recorded {supplier} into the comparison table."


def _run_send_reply(mailbox: GraphMailbox | None, tool_input: dict) -> str:
    message_id = tool_input.get("message_id")
    body = tool_input.get("body_text") or ""
    if not message_id:
        return "No message_id was given, so nothing was sent. Ask the coordinator for it."
    if not _autosend():
        print(f"\n[DRAFT -> {message_id}] (not sent; set FORGEFLOW_MANAGED_AGENT_AUTOSEND=true)\n{body}\n")
        return "Draft recorded. Not sent — autosend is disabled."
    mailbox.reply(message_id, body)
    print(f"\n[SENT -> {message_id}]\n")
    return "Reply sent."


RECORDED: list[dict] = []

# The thread the live session is reasoning about. record_extraction only carries
# supplier_name/classification/extraction, so the thread it belongs to has to
# come from here.
CURRENT_THREAD: dict = {}

TOOL_RUNNERS = {
    "read_comparison_table": lambda mb, i: _run_read_table(i),
    "record_extraction": lambda mb, i: _run_record(i),
    "send_reply": lambda mb, i: _run_send_reply(mb, i),
}


# ── Session ───────────────────────────────────────────────────────────────────

def _format_thread(messages: list[EmailMessage]) -> str:
    ordered = sorted(messages, key=lambda m: m.sent_at)
    parts = [f"RFQ email thread (subject: {ordered[-1].subject}):", ""]
    for msg in ordered:
        parts += [f"--- message_id: {msg.message_id}", f"From: {msg.sender}",
                  f"Sent: {msg.sent_at.isoformat()}", "", msg.body_text, ""]
    parts.append("Handle the latest message in this thread.")
    return "\n".join(parts)


def _run_session(client, agent_id: str, env_id: str, mailbox,
                 messages: list[EmailMessage]) -> str:
    """Run one coordinator session over a thread. Returns the session id."""
    global CURRENT_THREAD
    latest = max(messages, key=lambda m: m.sent_at)
    CURRENT_THREAD = {
        "thread_id": latest.thread_id,
        "subject": latest.subject,
        "sender": latest.sender,
        "buyer_email": latest.recipients or None,
        "latest_message_id": latest.message_id,
    }
    thread_text = _format_thread(messages)

    session = client.beta.sessions.create(
        agent=agent_id, environment_id=env_id, title="RFQ thread triage",
    )
    print(f"[trace] https://platform.claude.com/workspaces/default/sessions/{session.id}")

    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message",
                     "content": [{"type": "text", "text": thread_text}]}],
        )
        for event in stream:
            kind = event.type
            if kind == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)
            elif kind == "session.thread_created":
                print(f"\n[delegated to {getattr(event, 'agent_name', 'subagent')}]")
            elif kind == "agent.thread_message_sent":
                print(f"\n[-> {getattr(event, 'to_agent_name', 'subagent')}]")
            elif kind == "agent.thread_message_received":
                print(f"\n[<- {getattr(event, 'from_agent_name', 'subagent')}]")
            elif kind == "agent.custom_tool_use":
                runner = TOOL_RUNNERS.get(event.name)
                result = (runner(mailbox, event.input) if runner
                          else f"Unknown tool {event.name!r}.")
                reply = {
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": event.id,
                    "content": [{"type": "text", "text": result}],
                }
                # Subagent tool calls are cross-posted here; echo the thread they came from.
                thread_id = getattr(event, "session_thread_id", None)
                if thread_id:
                    reply["session_thread_id"] = thread_id
                client.beta.sessions.events.send(session_id=session.id, events=[reply])
            elif kind == "session.status_idle":
                if getattr(event.stop_reason, "type", None) == "requires_action":
                    continue
                break
            elif kind == "session.status_terminated":
                break

    # Sessions stay in the Console so their traces can be read. Archiving hides
    # them behind the "Active" filter, so it is opt-in rather than automatic.
    if os.environ.get("FORGEFLOW_ARCHIVE_SESSIONS", "").lower() in ("1", "true", "yes"):
        # The stream reports idle slightly before the queryable status catches up.
        for _ in range(10):
            if client.beta.sessions.retrieve(session_id=session.id).status != "running":
                client.beta.sessions.archive(session_id=session.id)
                break
            time.sleep(0.2)
    else:
        print(f"\n[session kept] {session.id} — visible in the Console")
    return session.id


# ── Polling ───────────────────────────────────────────────────────────────────

def _load_seen() -> set[str]:
    """Butterbase when configured: a runner's filesystem does not survive the job,
    which is why a second dispatch used to re-reply to threads it had answered."""
    if butterbase.enabled():
        return butterbase.seen_message_ids()
    return set(json.loads(SEEN_PATH.read_text())) if SEEN_PATH.exists() else set()


def _save_seen(seen: set[str]) -> None:
    if butterbase.enabled():
        return  # recorded per message in run_once, as each session finishes
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def run_once(client, mailbox, agent_id, env_id, seen: set[str]) -> int:
    messages = mailbox.fetch_recent()
    by_thread: dict[str, list[EmailMessage]] = {}
    for msg in messages:
        by_thread.setdefault(msg.thread_id, []).append(msg)

    processed = 0
    for msg in messages:
        if msg.message_id in seen:
            continue
        print(f"\n=== {msg.thread_id} / {msg.message_id} ===")
        session_id = _run_session(client, agent_id, env_id, mailbox, by_thread[msg.thread_id])
        seen.add(msg.message_id)
        if butterbase.enabled():
            # Per message, not at the end: a crash halfway through must not
            # leave already-answered threads looking unanswered on the next run.
            butterbase.mark_seen(msg.message_id, session_id, _autosend())
        processed += 1
    if processed:
        _save_seen(seen)
    return processed


def scan_once() -> None:
    """One pass over the inbox, then exit — the entry point for CI.

    `run` polls forever, which a workflow job cannot do. A runner also starts
    without data/managed_agent_seen.json, so every message reads as new.
    """
    client = _client()
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID")
    env_id = os.environ.get("FORGEFLOW_ENV_ID")
    if not agent_id or not env_id:
        raise SystemExit("Run `python -m forgeflow.managed_agent setup` first.")
    processed = run_once(client, GraphMailbox(), agent_id, env_id, _load_seen())
    print(f"processed={processed}")


def run(interval: int = POLL_INTERVAL_SECONDS) -> None:
    client = _client()
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID")
    env_id = os.environ.get("FORGEFLOW_ENV_ID")
    if not agent_id or not env_id:
        raise SystemExit("Run `python -m forgeflow.managed_agent setup` first.")
    mailbox = GraphMailbox()
    seen = _load_seen()
    print(f"Polling every {interval}s. Ctrl-C to stop.")
    while True:
        if not run_once(client, mailbox, agent_id, env_id, seen):
            print(".", end="", flush=True)
        time.sleep(interval)


# ── Health / test ─────────────────────────────────────────────────────────────

def health() -> None:
    ok = True

    def check(label, fn):
        nonlocal ok
        try:
            print(f"  [OK]  {label}" + (f": {r}" if (r := fn()) else ""))
        except Exception as exc:
            print(f"  [FAIL] {label}: {exc}")
            ok = False

    print("\n--- ForgeFlow Managed Agent Health Check ---")
    client = _client()
    coordinator_id = os.environ.get("FORGEFLOW_AGENT_ID", "")
    reply_id = os.environ.get("FORGEFLOW_REPLY_AGENT_ID", "")
    env_id = os.environ.get("FORGEFLOW_ENV_ID", "")

    check("ANTHROPIC_API_KEY", lambda: "set" if os.environ.get("ANTHROPIC_API_KEY") else _fail("not set"))
    check("FORGEFLOW_AGENT_ID", lambda: coordinator_id or _fail("not set — run setup"))
    check("FORGEFLOW_REPLY_AGENT_ID", lambda: reply_id or _fail("not set — run setup"))
    check("FORGEFLOW_ENV_ID", lambda: env_id or _fail("not set — run setup"))

    if coordinator_id:
        def _coord():
            a = client.beta.agents.retrieve(coordinator_id)
            roster = _roster(a)
            if not roster:
                raise RuntimeError("coordinator has no subagent roster — run deploy")
            return f"v{a.version}, roster {roster}"
        check("Coordinator reachable, roster wired", _coord)
    if reply_id:
        check("Reply subagent reachable",
              lambda: f"v{client.beta.agents.retrieve(reply_id).version}")
    if env_id:
        check("Environment reachable", lambda: client.beta.environments.retrieve(env_id).id)

    check("Outlook token", lambda: f"inbox reachable, {len(GraphMailbox().fetch_recent(top=1))} message(s)")
    check("Outlook identity", _token_identity)

    print("---")
    print("All checks passed. Ready to run.\n" if ok else "One or more checks failed.\n")
    if not ok:
        raise SystemExit(1)


def _fail(msg: str):
    raise RuntimeError(msg)


def _token_identity() -> str:
    """Which app registration and mailbox this token actually belongs to.

    Both come from the access token's own claims. Neither is a secret -- a client
    id is public by design -- and printing them is the only way to tell which of
    several app registrations a working credential came from. The token itself is
    never logged.
    """
    import base64

    token = refresh_access_token()
    parts = token.split(".")
    if len(parts) >= 2:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload))
            mailbox = (claims.get("upn") or claims.get("unique_name")
                       or claims.get("preferred_username"))
            return f"client_id={claims.get('appid')} mailbox={mailbox} scopes=[{claims.get('scp','')}]"
        except Exception:
            pass
    # Consumer (MSA) tokens are opaque, so ask Graph who we are instead. The
    # client id is not recoverable this way -- it only lives in the request.
    from forgeflow.graph import GraphMailbox as _GM

    me = _GM(access_token=token)._get("/me")
    return f"mailbox={me.get('userPrincipalName') or me.get('mail')} (opaque token, no client_id claim)"


def test_trigger(message_id: str | None = None) -> None:
    """Run one coordinator session against a real inbox thread. Draft-only by default."""
    client = _client()
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID")
    env_id = os.environ.get("FORGEFLOW_ENV_ID")
    if not agent_id or not env_id:
        raise SystemExit("Run setup first.")
    mailbox = GraphMailbox()
    messages = mailbox.fetch_recent(top=25)
    if not messages:
        raise SystemExit("No messages in inbox.")
    target = (next((m for m in messages if m.message_id == message_id), None)
              if message_id else messages[0])
    if target is None:
        raise SystemExit(f"message_id {message_id!r} not in the last 25 messages.")

    thread = [m for m in messages if m.thread_id == target.thread_id]
    print(f"\n=== TEST: {target.subject}")
    print(f"From    : {target.sender}")
    print(f"Autosend: {'ON — replies WILL be sent' if _autosend() else 'OFF — drafts only'}\n")
    _run_session(client, agent_id, env_id, mailbox, thread)
    if RECORDED:
        print(f"\n[table] coordinator recorded {len(RECORDED)} supplier state(s)")


def main() -> None:
    load_env()
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "setup":
        setup()
    elif command == "deploy":
        deploy()
    elif command == "health":
        health()
    elif command == "test":
        test_trigger(sys.argv[2] if len(sys.argv) > 2 else None)
    elif command == "run":
        run()
    elif command == "scan":
        scan_once()
    else:
        raise SystemExit(
            f"Unknown command: {command!r}. Use setup, deploy, health, test, scan, or run."
        )


if __name__ == "__main__":
    main()
