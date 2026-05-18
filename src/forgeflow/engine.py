from __future__ import annotations

from forgeflow.extractor import extract_case
from forgeflow.mailbox import Mailbox
from forgeflow.store import Store
from forgeflow.workflow import build_case, build_draft


class Engine:
    def __init__(self, store: Store, mailbox: Mailbox) -> None:
        self.store = store
        self.mailbox = mailbox

    def sync(self) -> dict[str, int]:
        ingested = 0
        updated_cases = 0
        drafted = 0
        for message in self.mailbox.fetch_messages():
            if self.store.has_message(message.message_id):
                continue
            self.store.save_message(message)
            self.store.record_event(
                message.thread_id,
                "message_ingested",
                {"message_id": message.message_id, "subject": message.subject},
            )
            ingested += 1

        for thread_id in self.store.list_thread_ids():
            messages = self.store.list_thread_messages(thread_id)
            extracted = extract_case(messages)
            case = build_case(thread_id, messages, extracted)
            self.store.upsert_case(case)
            self.store.record_event(
                thread_id,
                "case_updated",
                {
                    "classification": case.classification,
                    "status": case.status,
                    "next_action": case.next_action,
                },
            )
            updated_cases += 1
            draft = build_draft(case, messages)
            if draft is not None:
                self.store.replace_draft(draft)
                self.store.record_event(
                    thread_id,
                    "draft_created",
                    {"draft_type": draft.draft_type, "recipient": draft.recipient},
                )
                drafted += 1
        return {"ingested": ingested, "updated_cases": updated_cases, "drafted": drafted}

    def send(self, thread_id: str) -> str:
        draft = self.store.get_draft(thread_id)
        if draft is None:
            raise ValueError(f"No draft found for thread {thread_id}")
        out_path = self.mailbox.send_draft(draft)
        self.store.update_draft_status(thread_id, "sent")
        self.store.record_event(
            thread_id,
            "draft_sent",
            {"output_path": str(out_path), "recipient": draft.recipient},
        )
        return str(out_path)
