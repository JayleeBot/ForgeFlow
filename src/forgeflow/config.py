from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    inbox_dir: Path
    outbox_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppConfig":
        data_dir = root / "data"
        return cls(
            data_dir=data_dir,
            db_path=data_dir / "forgeflow.db",
            inbox_dir=data_dir / "sample_emails",
            outbox_dir=data_dir / "outbox",
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
