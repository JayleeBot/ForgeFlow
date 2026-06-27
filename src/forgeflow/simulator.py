from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from forgeflow.agent import process_thread
from forgeflow.models import EmailMessage
from forgeflow.parser import parse_email_file, parse_email_text
from forgeflow.processor import draft_reply
from forgeflow.store import connect, mark_processed, persist_processing_state, save_email


ROOT = Path(__file__).resolve().parents[2]

SCENARIOS: dict[str, list[str]] = {
    "offshelf_payment_terms": [
        "data/sample_emails/thread_offshelf_01_e1.eml",
        "data/sample_emails/thread_offshelf_01_e2.eml",
    ],
    "offshelf_complete": [
        "data/sample_emails/thread_offshelf_01_e1.eml",
        "data/sample_emails/thread_offshelf_01_e2.eml",
        "data/sample_emails/thread_offshelf_01_e3.eml",
        "data/sample_emails/thread_offshelf_01_e4.eml",
    ],
    "pcb_nre_missing": [
        "data/sample_emails/thread_pcb_01_e1.eml",
        "data/sample_emails/thread_pcb_01_e2.eml",
    ],
    "pcb_complete": [
        "data/sample_emails/thread_pcb_01_e1.eml",
        "data/sample_emails/thread_pcb_01_e2.eml",
        "data/sample_emails/thread_pcb_01_e3.eml",
        "data/sample_emails/thread_pcb_01_e4.eml",
    ],
    "supplier_question": [
        "data/sample_emails/08_supplier_question.eml",
    ],
}


def list_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "id": scenario_id,
            "label": scenario_id.replace("_", " ").title(),
            "files": files,
        }
        for scenario_id, files in SCENARIOS.items()
    ]


def run_scenario(scenario_id: str) -> dict[str, Any]:
    files = SCENARIOS.get(scenario_id)
    if not files:
        raise ValueError(f"Unknown simulator scenario: {scenario_id}")

    messages = [parse_email_file(ROOT / file) for file in files]
    return run_messages(scenario_id, messages, files)


def run_manual_thread(emails: list[str]) -> dict[str, Any]:
    cleaned = [email for email in emails if email.strip()]
    if not cleaned:
        raise ValueError("At least one manual email is required")
    messages = [
        parse_email_text(email, source_path=f"manual:{idx}")
        for idx, email in enumerate(cleaned, start=1)
    ]
    files = [message.source_path for message in messages]
    return run_messages("manual_playground", messages, files)


def run_messages(
    scenario_id: str,
    messages: list[EmailMessage],
    files: list[str],
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    with connect() as conn:
        for idx, message in enumerate(messages, start=1):
            save_email(conn, message)
            context = messages[:idx]
            result = process_thread(context)
            draft = draft_reply(message, result)
            mark_processed(conn, message.message_id, result, draft)
            persist_processing_state(conn, message, result, draft)
            payload = asdict(result)
            steps.append(
                {
                    "file": files[idx - 1],
                    "subject": message.subject,
                    "agent": _agent_for(payload["classification"]),
                    "classification": payload["classification"],
                    "result": payload,
                    "draft_reply": draft,
                }
            )
    return {"scenario": scenario_id, "steps": steps}


def _agent_for(classification: str) -> str:
    if classification == "rfq_sent":
        return "RFQ Schema Agent"
    if classification in ("supplier_quote", "supplier_reminder"):
        return "Supplier Extraction Agent + RFQ Action Agent"
    return "Router"
