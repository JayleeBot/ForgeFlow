from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from forgeflow import evals
from forgeflow.auth import device_login
from forgeflow.config import load_env
from forgeflow.graph import GraphMailbox
from forgeflow.parser import parse_email_file
from forgeflow.processor import ingest_messages, process_pending
from forgeflow.server import run_server
from forgeflow.store import connect, mark_reply_sent, recent_interactions, unsent_draft_replies
from forgeflow.store import rebuild_state_from_interactions, rfq_states


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
    sub.add_parser("rebuild-state")
    sub.add_parser("list-rfqs")
    send = sub.add_parser("send-replies")
    send.add_argument("--yes", action="store_true")
    watch = sub.add_parser("watch-outlook")
    watch.add_argument("--seconds", type=int, default=int(os.environ.get("FORGEFLOW_POLL_SECONDS", "60")))
    sub.add_parser("dashboard").add_argument("--port", type=int, default=8000)
    sub.add_parser("list")
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("case_file", nargs="?", default="data/eval_cases/eval_cases.json")
    evaluate.add_argument("--save", help="write this run's grades to a JSON file")
    evaluate.add_argument("--compare", help="diff against a previously saved run")
    evaluate.add_argument("--workers", type=int, default=evals.DEFAULT_WORKERS)
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
    elif args.cmd == "rebuild-state":
        with connect() as conn:
            print(f"rebuilt={rebuild_state_from_interactions(conn)}")
    elif args.cmd == "list-rfqs":
        with connect() as conn:
            print(json.dumps(rfq_states(conn), indent=2))
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
        run_eval(args)


def run_eval(args) -> None:
    cases = evals.load_cases(Path(args.case_file))
    print(f"Running {len(cases)} cases across {args.workers} workers...\n", flush=True)
    results = evals.run_evals(cases, workers=args.workers)
    print(evals.format_report(results))

    if args.save:
        path = Path(args.save)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evals.to_json(results), indent=2))
        print(f"\nSaved run to {path}")

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text())
        print(f"\n--- vs {args.compare} ---")
        print(evals.compare_runs(baseline, results))


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
