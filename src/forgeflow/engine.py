from __future__ import annotations

import re
from datetime import datetime

from forgeflow.config import AppConfig
from forgeflow.extractor import extract_case
from forgeflow.mailbox import Mailbox
from forgeflow.store import Store
from forgeflow.workflow import build_case, build_draft

_EMAIL_RE = re.compile(r"<([^>]+)>")


def _sender_email(sender: str) -> str:
    m = _EMAIL_RE.search(sender)
    return (m.group(1) if m else sender).strip().lower()


class Engine:
    def __init__(self, store: Store, mailbox: Mailbox, config: AppConfig) -> None:
        self.store = store
        self.mailbox = mailbox
        self.config = config

    def sync(self) -> dict[str, int]:
        ingested = 0
        updated_cases = 0
        drafted = 0

        # Track which new senders appeared in each thread this sync run.
        # Used to detect buyer replies to pending_buyer_input cases.
        new_senders_by_thread: dict[str, list[str]] = {}

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
            new_senders_by_thread.setdefault(message.thread_id, []).append(
                _sender_email(message.sender)
            )

        for thread_id in self.store.list_thread_ids():
            existing_case = self.store.get_case(thread_id)
            messages = self.store.list_thread_messages(thread_id)
            extracted = extract_case(messages)

            # Buyer reply detection: if the case was pending_buyer_input and a new
            # message arrived from someone who is neither the agent nor the supplier,
            # the buyer has replied — advance the state machine.
            buyer_replied = False
            if (
                existing_case
                and existing_case.status == "pending_buyer_input"
                and thread_id in new_senders_by_thread
            ):
                supplier_email = existing_case.supplier_email or ""
                for sender in new_senders_by_thread[thread_id]:
                    if sender != self.config.agent_email.lower() and sender != supplier_email.lower():
                        buyer_replied = True
                        break

            case = build_case(thread_id, messages, extracted, buyer_replied)
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

            draft = build_draft(case, messages, self.config.agent_email)
            if draft is not None and self._should_create_draft(case, draft):
                self.store.replace_draft(draft)
                self.store.record_event(
                    thread_id,
                    "draft_created",
                    {"draft_type": draft.draft_type, "recipient": draft.recipient},
                )
                drafted += 1

        return {"ingested": ingested, "updated_cases": updated_cases, "drafted": drafted}

    def _should_create_draft(self, case, draft) -> bool:
        existing = self.store.get_draft(case.thread_id)
        # Never overwrite a draft the buyer hasn't acted on yet
        if existing and existing.status == "draft" and existing.draft_type == draft.draft_type:
            return False
        # For missing_info_request retries: only resend after followup_retry_days
        if draft.draft_type == "missing_info_request" and case.last_followup_sent_at is not None:
            days_since = (datetime.utcnow() - case.last_followup_sent_at).days
            if days_since < self.config.followup_retry_days:
                return False
        return True

    def send(self, thread_id: str) -> str:
        draft = self.store.get_draft(thread_id)
        if draft is None:
            raise ValueError(f"No draft found for thread {thread_id}")
        if draft.draft_type == "flag_buyer":
            raise ValueError(
                f"Thread {thread_id} has a buyer flag — this is a dashboard notification, not an outbound email."
            )
        out_path = self.mailbox.send_draft(draft)
        self.store.update_draft_status(thread_id, "sent")
        if draft.draft_type in ("missing_info_request", "acknowledgement"):
            self.store.mark_followup_sent(thread_id)
        self.store.record_event(
            thread_id,
            "draft_sent",
            {"output_path": str(out_path), "recipient": draft.recipient},
        )
        return str(out_path)
