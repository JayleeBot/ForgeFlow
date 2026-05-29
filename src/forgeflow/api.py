from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from forgeflow.config import AppConfig
from forgeflow.engine import Engine
from forgeflow.mailbox import build_mailbox
from forgeflow.store import Store

ROOT = Path.cwd()
PROVIDER = os.getenv("FORGEFLOW_PROVIDER", "local")
POLL_SECONDS = int(os.getenv("FORGEFLOW_POLL_SECONDS", "60"))
DASHBOARD = Path(__file__).parent / "dashboard.html"


@contextmanager
def _engine() -> Iterator[Engine]:
    """Open a request-scoped engine. A fresh SQLite connection per call keeps
    each request/thread isolated (SQLite connections are not shared across threads)."""
    config = AppConfig.from_root(ROOT)
    config.ensure_dirs()
    store = Store(config.db_path)
    store.initialize()
    mailbox = build_mailbox(PROVIDER, config.inbox_dir, config.outbox_dir)
    try:
        yield Engine(store, mailbox)
    finally:
        store.close()


def _run_sync() -> dict[str, int]:
    with _engine() as engine:
        return engine.sync()


async def _poller() -> None:
    while True:
        try:
            stats = await asyncio.to_thread(_run_sync)
            print(f"[poller] sync: {stats}")
        except Exception as exc:  # keep the loop alive across transient failures
            print(f"[poller] sync failed: {exc}")
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poller()) if POLL_SECONDS > 0 else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()


app = FastAPI(title="ForgeFlow", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "provider": PROVIDER, "poll_seconds": POLL_SECONDS}


@app.post("/sync")
def sync() -> dict[str, int]:
    return _run_sync()


@app.get("/cases")
def cases() -> list[dict]:
    with _engine() as engine:
        return [asdict(case) for case in engine.store.list_cases()]


@app.get("/drafts")
def drafts() -> list[dict]:
    with _engine() as engine:
        return [asdict(draft) for draft in engine.store.list_drafts()]


@app.post("/drafts/{thread_id}/send")
def send(thread_id: str) -> dict:
    with _engine() as engine:
        try:
            out_path = engine.send(thread_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"thread_id": thread_id, "sent": out_path}


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD)
