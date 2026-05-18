# ForgeFlow

ForgeFlow is a local-first prototype for an email-native quote operations assistant. The current version supports a local `.eml` test inbox and an Outlook-backed production adapter through Microsoft Graph.

## Current scope

- Shared-mailbox style quote inbox workflow
- SQLite persistence for threads, cases, drafts, and event history
- Local `.eml` ingestion for fast testing
- Outlook shared-mailbox integration via Microsoft Graph
- RFQ triage and missing-information detection
- Draft generation for clarification, status replies, and lightweight follow-up

## Project structure

- `src/forgeflow/`: core app code
- `data/sample_inbox/`: sample quote-related emails
- `data/outbox/`: local sent-output directory created at runtime
- `data/forgeflow.db`: SQLite database created at runtime

## Quick start

Use the source tree directly with the local test inbox:

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

## Outlook mode

ForgeFlow can also read from and send through an Outlook mailbox using Microsoft Graph.

Required environment variables:

```bash
export FORGEFLOW_OUTLOOK_ACCESS_TOKEN="..."
export FORGEFLOW_OUTLOOK_MAILBOX="quotes@company.com"
```

Optional environment variables:

```bash
export FORGEFLOW_OUTLOOK_FOLDER="Inbox"
export FORGEFLOW_OUTLOOK_TOP="25"
```

Run the same commands with `--provider outlook`:

```bash
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook sync
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook list-cases
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook list-drafts
PYTHONPATH=src python3 -m forgeflow.cli --provider outlook send <thread_id>
```

In Outlook mode:

- `sync` pulls recent messages from the configured mailbox folder using Microsoft Graph
- thread IDs come from Outlook `conversationId`
- `send` sends the draft through the configured Outlook mailbox and marks it as sent locally

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

- replace the heuristic Graph token flow with tenant-specific OAuth or app credentials
- replace heuristic extraction with an LLM-assisted extractor
- add a review dashboard on top of the SQLite store
- add scheduled follow-up jobs instead of manual sync

## Notes

- This prototype is local-only.
- Outlook integration requires a valid Microsoft Graph access token.
- Local mode simulates draft sending by writing text files into the outbox.
