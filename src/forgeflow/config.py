from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    inbox_dir: Path
    outbox_dir: Path
    agent_email: str = ""
    followup_retry_days: int = 3

    @classmethod
    def from_root(cls, root: Path) -> "AppConfig":
        data_dir = root / "data"
        return cls(
            data_dir=data_dir,
            db_path=data_dir / "forgeflow.db",
            inbox_dir=data_dir / "sample_emails",
            outbox_dir=data_dir / "outbox",
            agent_email=os.environ.get("FORGEFLOW_AGENT_EMAIL", ""),
            followup_retry_days=int(os.environ.get("FORGEFLOW_FOLLOWUP_RETRY_DAYS", "3")),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
