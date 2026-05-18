# ForgeFlow

ForgeFlow is a local-first prototype for an email-native quote operations assistant. The current version ingests `.eml` files from a local inbox, turns threads into quote cases, generates recommended next actions, and writes approved outbound drafts to a local outbox.

## Current scope

- Shared-mailbox style quote inbox workflow
- SQLite persistence for threads, cases, drafts, and event history
- Local `.eml` ingestion for fast testing
- RFQ triage and missing-information detection
- Draft generation for clarification, status replies, and lightweight follow-up

## Project structure

- `src/forgeflow/`: core app code
- `data/sample_inbox/`: sample quote-related emails
- `data/outbox/`: local sent-output directory created at runtime
- `data/forgeflow.db`: SQLite database created at runtime

## Quick start

Use the source tree directly:

```bash
PYTHONPATH=src python3 -m forgeflow.cli init
PYTHONPATH=src python3 -m forgeflow.cli sync
PYTHONPATH=src python3 -m forgeflow.cli list-cases
PYTHONPATH=src python3 -m forgeflow.cli list-drafts
```

Send one generated draft to the local outbox:

```bash
PYTHONPATH=src python3 -m forgeflow.cli send <thread_id>
```

You can also install the package locally and use the `forgeflow` command:

```bash
python3 -m pip install -e .
forgeflow sync
```

## How the prototype works

1. `.eml` files in `data/sample_inbox/` are parsed into normalized messages.
2. Messages are grouped into lightweight threads.
3. Each thread is classified into a quote workflow type.
4. Structured fields are extracted:
   - customer email
   - due date
   - part numbers
   - quantities
   - missing fields
5. ForgeFlow creates or updates a local quote case in SQLite.
6. If needed, ForgeFlow generates a draft clarification or follow-up email.
7. `send` writes the outbound email content to `data/outbox/`.

## Extension points

The current local mailbox adapter is intentionally simple. To extend this toward production:

- replace `LocalMailbox` with a Gmail API or Microsoft Graph adapter
- replace heuristic extraction with an LLM-assisted extractor
- add a review dashboard on top of the SQLite store
- add scheduled follow-up jobs instead of manual sync

## Notes

- This prototype is local-only.
- No live email provider integration is included yet.
- Draft sending is simulated by writing text files into the outbox.
