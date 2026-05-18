from __future__ import annotations

import argparse
from pathlib import Path

from forgeflow.config import AppConfig
from forgeflow.engine import Engine
from forgeflow.mailbox import build_mailbox
from forgeflow.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ForgeFlow local-first prototype")
    parser.add_argument(
        "--provider",
        choices=["local", "outlook"],
        default="local",
        help="Mailbox provider to use",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize local data directories and SQLite database")
    subparsers.add_parser("sync", help="Ingest local emails and update cases")
    subparsers.add_parser("list-cases", help="List current cases")
    subparsers.add_parser("list-drafts", help="List current drafts")

    send_parser = subparsers.add_parser("send", help="Send a draft to the local outbox")
    send_parser.add_argument("thread_id", help="Thread ID to send")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path.cwd()
    config = AppConfig.from_root(root)
    config.ensure_dirs()
    store = Store(config.db_path)
    store.initialize()
    mailbox = build_mailbox(args.provider, config.inbox_dir, config.outbox_dir)
    engine = Engine(store, mailbox)

    try:
        if args.command == "init":
            print(f"Initialized ForgeFlow in {config.data_dir}")
            return
        if args.command == "sync":
            stats = engine.sync()
            print(
                f"Ingested {stats['ingested']} messages, "
                f"updated {stats['updated_cases']} cases, created {stats['drafted']} drafts"
            )
            return
        if args.command == "list-cases":
            for case in store.list_cases():
                print(
                    f"{case.thread_id} | {case.status} | {case.classification} | "
                    f"{case.customer_email or '-'} | {case.next_action or '-'}"
                )
                print(f"  {case.summary}")
            return
        if args.command == "list-drafts":
            for draft in store.list_drafts():
                print(
                    f"{draft.thread_id} | {draft.status} | "
                    f"{draft.draft_type} -> {draft.recipient}"
                )
                print(f"  Subject: {draft.subject}")
            return
        if args.command == "send":
            out_path = engine.send(args.thread_id)
            print(f"Draft written to {out_path}")
            return
    finally:
        store.close()


if __name__ == "__main__":
    main()
