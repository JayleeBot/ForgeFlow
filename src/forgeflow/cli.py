from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from forgeflow.agent import process_thread
from forgeflow.auth import device_login
from forgeflow.config import load_env
from forgeflow.graph import GraphMailbox
from forgeflow.parser import parse_email_file
from forgeflow.processor import ingest_messages, process_pending
from forgeflow.server import run_server
from forgeflow.store import connect, mark_reply_sent, recent_interactions, unsent_draft_replies


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="forgeflow")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-local").add_argument("path", nargs="?", default="data/sample_inbox")
    sub.add_parser("sync-outlook")
    login = sub.add_parser("login-outlook")
    login.add_argument("--tenant", default=os.environ.get("FORGEFLOW_AZURE_TENANT_ID") or "consumers")
    login.add_argument("--client-id", default=os.environ.get("FORGEFLOW_AZURE_CLIENT_ID"))
    sub.add_parser("process")
    send = sub.add_parser("send-replies")
    send.add_argument("--yes", action="store_true")
    watch = sub.add_parser("watch-outlook")
    watch.add_argument("--seconds", type=int, default=int(os.environ.get("FORGEFLOW_POLL_SECONDS", "60")))
    sub.add_parser("dashboard").add_argument("--port", type=int, default=8000)
    sub.add_parser("list")
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("case_file", nargs="?", default="data/eval_cases/eval_cases.json")
    args = parser.parse_args()

    if args.cmd == "sync-local":
        messages = [parse_email_file(path) for path in sorted(Path(args.path).glob("*.eml"))]
        print(f"ingested={ingest_messages(messages)}")
    elif args.cmd == "sync-outlook":
        print(f"ingested={ingest_messages(GraphMailbox().fetch_recent())}")
    elif args.cmd == "login-outlook":
        if not args.client_id:
            raise SystemExit("Set FORGEFLOW_AZURE_CLIENT_ID in .env or pass --client-id")
        device_login(args.client_id, args.tenant)
    elif args.cmd == "process":
        print(f"processed={process_pending()}")
    elif args.cmd == "send-replies":
        send_replies(args.yes)
    elif args.cmd == "watch-outlook":
        watch_outlook(args.seconds)
    elif args.cmd == "dashboard":
        run_server(port=args.port)
    elif args.cmd == "list":
        with connect() as conn:
            print(json.dumps(recent_interactions(conn), indent=2))
    elif args.cmd == "eval":
        print(json.dumps(run_eval(Path(args.case_file)), indent=2))


def run_eval(path: Path) -> list[dict]:
    cases = json.loads(path.read_text())
    results = []
    for case in cases:
        files = case.get("thread_emails") or [case["email_file"]]
        messages = [parse_email_file(Path(file)) for file in files]
        result = process_thread(messages)
        results.append({
            "email_file": case["email_file"],
            "expected_classification": case["expected_classification"],
            "classification": result.classification,
            "pass": result.classification == case["expected_classification"],
            "result": asdict(result),
        })
    return results


def watch_outlook(seconds: int) -> None:
    while True:
        ingested = ingest_messages(GraphMailbox().fetch_recent())
        processed = process_pending()
        print(f"ingested={ingested} processed={processed}", flush=True)
        time.sleep(seconds)


def send_replies(confirmed: bool) -> None:
    with connect() as conn:
        drafts = unsent_draft_replies(conn)
        if not drafts:
            print("No unsent draft replies.")
            return
        if not confirmed:
            print(json.dumps(drafts, indent=2))
            print("Run again with --yes to send these replies.")
            return
        mailbox = GraphMailbox()
        for draft in drafts:
            mailbox.reply(draft["message_id"], draft["draft_reply"])
            mark_reply_sent(conn, draft["message_id"])
            print(f"sent={draft['subject']}")


if __name__ == "__main__":
    main()
