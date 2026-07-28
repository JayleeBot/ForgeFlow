"""Run ForgeFlow's RFQ triage as a Claude Managed Agent.

Architecture (host-side custom tools + host-side poller):

  * Anthropic hosts the agent loop in a per-session container. The agent's job
    is RFQ triage: read an email thread, decide whether a supplier follow-up is
    needed, and either draft/send a reply or flag the buyer.
  * ForgeFlow keeps ownership of the mailbox. `GraphMailbox` already fetches mail
    and auto-refreshes the delegated Outlook token, so the token NEVER enters the
    Anthropic sandbox. The agent asks for a reply via the `send_reply` custom
    tool; this process executes it against Microsoft Graph.

Usage:

    python -m forgeflow.managed_agent setup     # one-time: create env + agent
    python -m forgeflow.managed_agent run        # poll inbox and respond

`setup` stores FORGEFLOW_AGENT_ID / FORGEFLOW_ENV_ID in .env. Re-run only when
you want to change the agent's config (each `agents.create` makes a new agent —
to tweak an existing one, use `agents.update`, not `setup`).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic

from forgeflow.config import load_env, set_env_values
from forgeflow.graph import GraphMailbox
from forgeflow.models import EmailMessage

MODEL = {"id": "claude-opus-5", "effort": "xhigh"}
SEEN_PATH = Path("data/managed_agent_seen.json")
POLL_INTERVAL_SECONDS = 60

SYSTEM_PROMPT = """\
You are ForgeFlow's RFQ triage agent for a procurement team. The buyer CCs you on
outbound RFQ emails; suppliers reply with quotes. You read one email thread at a
time and take exactly one action.

Workflow:
1. Identify the latest email in the thread.
2. If it is a supplier quote or reminder, check whether it contains the required
   fields: price breaks, production lead time, MOQ, payment terms, NRE, country
   of origin, and the manufacturer part number (MFG P/N) matching the RFQ.
3. Choose ONE action:
   - Missing required fields -> call `send_reply` with a short, polite follow-up
     asking ONLY for the specific missing fields.
   - Supplier quoted a different MFG P/N than the RFQ, or asks the buyer a
     question -> call `send_reply` with a message that begins "[FLAG FOR BUYER]"
     and clearly states what needs the buyer's decision. Do NOT ask the supplier.
   - All required fields present, nothing blocking -> do not reply; briefly state
     the quote is ready for human review.

Rules:
- Extract only what is actually present in the thread. Never invent values.
- Keep replies concise and professional. Sign as "ForgeFlow".
- Take at most one `send_reply` action per thread.
"""

SEND_REPLY_TOOL = {
    "type": "custom",
    "name": "send_reply",
    "description": (
        "Reply to a message in the email thread. Provide the message_id of the "
        "email you are replying to and the reply body text. Use this only when a "
        "supplier follow-up is needed or the buyer must be flagged."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "The message_id of the email being replied to.",
            },
            "body_text": {
                "type": "string",
                "description": "The reply body to send.",
            },
        },
        "required": ["message_id", "body_text"],
    },
}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def setup() -> None:
    """Create the environment and agent once; persist their IDs to .env.

    Refuses to run if IDs already exist — creating a second agent orphans the
    first. Use `deploy` to push config changes to the existing agent.
    """
    client = _client()
    if os.environ.get("FORGEFLOW_AGENT_ID") or os.environ.get("FORGEFLOW_ENV_ID"):
        raise SystemExit(
            "FORGEFLOW_AGENT_ID / FORGEFLOW_ENV_ID are already set in .env.\n"
            "Use `python -m forgeflow.managed_agent deploy` to update the existing "
            "agent, or clear those keys first to provision a new one."
        )
    env = client.beta.environments.create(
        name="forgeflow-rfq",
        config={"type": "cloud", "networking": {"type": "unrestricted"}},
    )
    agent = client.beta.agents.create(
        name="ForgeFlow RFQ Agent",
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=[SEND_REPLY_TOOL],
    )
    set_env_values({"FORGEFLOW_AGENT_ID": agent.id, "FORGEFLOW_ENV_ID": env.id})
    print(f"Created environment {env.id} and agent {agent.id} (v{agent.version}).")
    print("Saved FORGEFLOW_AGENT_ID and FORGEFLOW_ENV_ID to .env.")


def deploy() -> None:
    """Push the model / system prompt / tools in this file to the existing agent.

    Each update creates a new immutable agent version; running sessions keep the
    version they were created with.
    """
    client = _client()
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID")
    if not agent_id:
        raise SystemExit("No FORGEFLOW_AGENT_ID in .env — run `setup` first.")
    current = client.beta.agents.retrieve(agent_id)
    agent = client.beta.agents.update(
        agent_id,
        version=current.version,  # optimistic lock: 409 if someone else updated
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=[SEND_REPLY_TOOL],
    )
    print(f"Updated agent {agent.id}: v{current.version} -> v{agent.version}")
    print(f"  model: {agent.model}")


def _load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def _format_thread(messages: list[EmailMessage]) -> str:
    ordered = sorted(messages, key=lambda m: m.sent_at)
    parts = [f"RFQ email thread (subject: {ordered[-1].subject}):", ""]
    for msg in ordered:
        parts.append(f"--- message_id: {msg.message_id}")
        parts.append(f"From: {msg.sender}")
        parts.append(f"Sent: {msg.sent_at.isoformat()}")
        parts.append("")
        parts.append(msg.body_text)
        parts.append("")
    parts.append(
        "Decide the single correct action for the latest message. "
        "If a reply is warranted, call send_reply with that message_id."
    )
    return "\n".join(parts)


def _execute_send_reply(mailbox: GraphMailbox, tool_input: dict) -> str:
    message_id = tool_input["message_id"]
    body_text = tool_input["body_text"]
    autosend = os.environ.get("FORGEFLOW_MANAGED_AGENT_AUTOSEND", "").lower() in ("1", "true", "yes")
    if not autosend:
        print(f"\n[DRAFT for {message_id}] (not sent — set FORGEFLOW_MANAGED_AGENT_AUTOSEND=true to send)\n{body_text}\n")
        return "Draft recorded. Not sent (autosend disabled)."
    mailbox.reply(message_id, body_text)
    print(f"\n[SENT reply to {message_id}]\n")
    return "Reply sent."


def _run_session(client: anthropic.Anthropic, agent_id: str, env_id: str,
                 mailbox: GraphMailbox, thread_text: str) -> None:
    session = client.beta.sessions.create(
        agent=agent_id,
        environment_id=env_id,
        title="RFQ thread triage",
    )
    print(f"[trace] https://platform.claude.com/workspaces/default/sessions/{session.id}")
    # Stream-first: open the stream before sending the kickoff message.
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": thread_text}]}],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)
            elif event.type == "agent.custom_tool_use":
                result = _execute_send_reply(mailbox, event.input)
                client.beta.sessions.events.send(
                    session_id=session.id,
                    events=[{
                        "type": "user.custom_tool_result",
                        "custom_tool_use_id": event.id,
                        "content": [{"type": "text", "text": result}],
                    }],
                )
            elif event.type == "session.status_idle":
                if getattr(event.stop_reason, "type", None) == "requires_action":
                    continue  # waiting on our tool result — keep streaming
                break  # end_turn / retries_exhausted — terminal
            elif event.type == "session.status_terminated":
                break
    # The stream reports idle slightly before the session's queryable status
    # catches up; archiving too early 400s with "cannot archive while running".
    for _ in range(10):
        if client.beta.sessions.retrieve(session_id=session.id).status != "running":
            client.beta.sessions.archive(session_id=session.id)
            break
        time.sleep(0.2)


def run_once(client: anthropic.Anthropic, mailbox: GraphMailbox,
             agent_id: str, env_id: str, seen: set[str]) -> int:
    messages = mailbox.fetch_recent()
    by_thread: dict[str, list[EmailMessage]] = {}
    for msg in messages:
        by_thread.setdefault(msg.thread_id, []).append(msg)

    processed = 0
    for msg in messages:
        if msg.message_id in seen:
            continue
        thread_text = _format_thread(by_thread[msg.thread_id])
        print(f"\n=== Triaging thread {msg.thread_id} (latest {msg.message_id}) ===")
        _run_session(client, agent_id, env_id, mailbox, thread_text)
        seen.add(msg.message_id)
        processed += 1
    if processed:
        _save_seen(seen)
    return processed


def run(interval: int = POLL_INTERVAL_SECONDS) -> None:
    client = _client()
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID")
    env_id = os.environ.get("FORGEFLOW_ENV_ID")
    if not agent_id or not env_id:
        raise SystemExit("Run `python -m forgeflow.managed_agent setup` first.")
    mailbox = GraphMailbox()
    seen = _load_seen()
    print(f"Polling inbox every {interval}s. Ctrl-C to stop.")
    while True:
        count = run_once(client, mailbox, agent_id, env_id, seen)
        if not count:
            print(".", end="", flush=True)
        time.sleep(interval)


def health() -> None:
    """Check all credentials and the deployed agent/environment are reachable."""
    ok = True

    def check(label: str, fn):
        nonlocal ok
        try:
            result = fn()
            print(f"  [OK]  {label}" + (f": {result}" if result else ""))
        except Exception as exc:
            print(f"  [FAIL] {label}: {exc}")
            ok = False

    print("\n--- ForgeFlow Managed Agent Health Check ---")

    # 1. Anthropic API
    client = _client()
    check("ANTHROPIC_API_KEY", lambda: "set" if os.environ.get("ANTHROPIC_API_KEY") else (_ for _ in ()).throw(RuntimeError("not set")))

    # 2. Agent + environment exist on Anthropic
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID", "")
    env_id = os.environ.get("FORGEFLOW_ENV_ID", "")
    check("FORGEFLOW_AGENT_ID", lambda: agent_id or (_ for _ in ()).throw(RuntimeError("not set — run setup")))
    check("FORGEFLOW_ENV_ID", lambda: env_id or (_ for _ in ()).throw(RuntimeError("not set — run setup")))
    if agent_id:
        check("Agent reachable on Anthropic", lambda: client.beta.agents.retrieve(agent_id).id)
    if env_id:
        check("Environment reachable on Anthropic", lambda: client.beta.environments.retrieve(env_id).id)

    # 3. Outlook access token
    check("FORGEFLOW_OUTLOOK_ACCESS_TOKEN", lambda: "set" if os.environ.get("FORGEFLOW_OUTLOOK_ACCESS_TOKEN") else (_ for _ in ()).throw(RuntimeError("not set")))
    check("FORGEFLOW_OUTLOOK_AUTH_MODE", lambda: os.environ.get("FORGEFLOW_OUTLOOK_AUTH_MODE", "(not set)"))

    # 4. Live Graph call — fetch 1 message (triggers auto-refresh on 401)
    def _graph_ping():
        mailbox = GraphMailbox()
        msgs = mailbox.fetch_recent(top=1)
        return f"inbox reachable, got {len(msgs)} message(s)"
    check("Microsoft Graph / Outlook token", _graph_ping)

    print("---")
    if ok:
        print("All checks passed. Ready to run.\n")
    else:
        print("One or more checks failed. Fix the issues above, then retry.\n")
        raise SystemExit(1)


def test_trigger(message_id: str | None = None) -> None:
    """
    Pull the most recent email from inbox and run one managed-agent session against it.
    Pass a specific message_id to target that thread, or omit to use the latest message.
    Replies are DRAFT-only unless FORGEFLOW_MANAGED_AGENT_AUTOSEND=true.
    """
    client = _client()
    agent_id = os.environ.get("FORGEFLOW_AGENT_ID")
    env_id = os.environ.get("FORGEFLOW_ENV_ID")
    if not agent_id or not env_id:
        raise SystemExit("Run setup first.")
    mailbox = GraphMailbox()
    messages = mailbox.fetch_recent(top=25)
    if not messages:
        raise SystemExit("No messages in inbox — nothing to test with.")

    if message_id:
        target = next((m for m in messages if m.message_id == message_id), None)
        if not target:
            raise SystemExit(f"message_id {message_id!r} not found in the last 25 messages.")
    else:
        target = messages[0]

    # Build thread: all messages sharing this thread_id
    thread_msgs = [m for m in messages if m.thread_id == target.thread_id]
    thread_text = _format_thread(thread_msgs)
    print(f"\n=== TEST: triaging thread {target.thread_id} (message {target.message_id}) ===")
    print(f"Subject : {target.subject}")
    print(f"From    : {target.sender}")
    print(f"Sent    : {target.sent_at.isoformat()}")
    autosend = os.environ.get("FORGEFLOW_MANAGED_AGENT_AUTOSEND", "").lower() in ("1", "true", "yes")
    print(f"Autosend: {'ON — will actually send replies' if autosend else 'OFF — replies are drafts only'}")
    print()
    _run_session(client, agent_id, env_id, mailbox, thread_text)
    print()


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
        # Optional: python -m forgeflow.managed_agent test <message_id>
        msg_id = sys.argv[2] if len(sys.argv) > 2 else None
        test_trigger(msg_id)
    elif command == "run":
        run()
    else:
        raise SystemExit(f"Unknown command: {command!r}. Use 'setup', 'deploy', 'health', 'test', or 'run'.")


if __name__ == "__main__":
    main()
