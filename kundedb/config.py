"""File locations.

Development (python app.py): data in the project's data/ folder.
Packaged (PyInstaller, sys.frozen): a per-user folder – %APPDATA%\\Kundedatabase on Windows – never next
to the exe, and not Documents (OneDrive often syncs it, which is bad for SQLite and personal data).

KUNDEDB_DATA overrides the data folder in both modes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Kundedatabase"
PROJECT_DIR = Path(__file__).resolve().parent.parent
BACKUP_KEEP = 20
DATA_ENV = "KUNDEDB_DATA"


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    db_file: Path
    backups_dir: Path
    export_dir: Path

    @property
    def log_file(self) -> Path:
        return self.data_dir / "kundedatabase.log"

    @property
    def filters_file(self) -> Path:
        """Named selection criteria (JSON)."""
        return self.data_dir / "utvalg.json"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def default_data_dir() -> Path:
    if not is_frozen():
        return PROJECT_DIR / "data"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def get_paths() -> Paths:
    env = os.environ.get(DATA_ENV)
    data_dir = Path(env).expanduser().resolve() if env else default_data_dir()
    return Paths(
        data_dir=data_dir,
        db_file=data_dir / "kundedatabase.db",
        backups_dir=data_dir / "backups",
        export_dir=data_dir / "export",
    )


def ensure_dirs(paths: Paths) -> None:
    for d in (paths.data_dir, paths.backups_dir, paths.export_dir):
        d.mkdir(parents=True, exist_ok=True)
