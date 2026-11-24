"""SQLite connection, schema migrations and startup backup."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

BACKUP_PREFIX = "kundedatabase_"

_NOW = "(strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))"

_SCHEMA_V1 = f"""
CREATE TABLE customer (
  id INTEGER PRIMARY KEY,
  company TEXT,                              -- Firma
  place TEXT,                                -- Sted
  category TEXT,                             -- Kategori
  full_name TEXT,                            -- Fullt navn
  email TEXT,                                -- E-post
  address TEXT,                              -- Adresse 1
  postcode TEXT,                             -- Postnummer: text, 4 digits with leading zeros
  org_nr TEXT,                               -- Org.nr: text, 9 digits when valid
  gnr_bnr TEXT,                              -- Gnr og bnr as written ("12/3", "12/3/0", "12-3, 14/1")
  gnr INTEGER,                               -- first property parsed from gnr_bnr
  bnr INTEGER,
  kommunenr TEXT,                            -- Kommunenr: text, 4 digits with leading zeros
  phone TEXT,                                -- Telefon - Mobilnr.: text
  lat REAL,                                  -- WGS84 / EUREF89
  lon REAL,
  geocode_source TEXT CHECK (geocode_source IN ('gnr_bnr', 'adresse', 'postnummer', 'manuell')),
  geocode_date TEXT,                         -- when coordinates were last looked up (also when not found)
  geocode_note TEXT,                         -- what was found, or why not
  notes TEXT,
  created TEXT NOT NULL DEFAULT {_NOW},
  updated TEXT NOT NULL DEFAULT {_NOW},
  CHECK ((lat IS NULL) = (lon IS NULL)),
  CHECK (lat IS NULL OR geocode_source IS NOT NULL)
);
CREATE INDEX idx_customer_org_nr ON customer(org_nr);
"""

# 2: settings (map background, optional Google Maps API key). Key/value, values are text.
_V2_SETTINGS = """
CREATE TABLE setting (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO setting (key, value) VALUES ('map_background', 'kartverket'), ('google_maps_api_key', '');
"""

# 3: which fruit the customer grows ("Eple, Pære, Plomme, Kirsebær"; canonical names, comma-separated).
_V3_FRUIT = """
ALTER TABLE customer ADD COLUMN fruit TEXT;
"""

# Append only. Never edit a migration that has shipped; add a new one.
MIGRATIONS: list[str] = [_SCHEMA_V1, _V2_SETTINGS, _V3_FRUIT]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(db_file: Path | str) -> sqlite3.Connection:
    # Autocommit mode: transactions are explicit via transaction() / migrations.
    conn = sqlite3.connect(db_file, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    return conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each in its own transaction. Returns the new version."""
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"Databasen har skjemaversjon {current}, men programmet kjenner bare "
            f"til versjon {len(MIGRATIONS)}. Bruk en nyere versjon av programmet."
        )
    for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        script = (
            f"BEGIN;\n{sql}\n"
            f"INSERT INTO schema_version (version, applied_at) VALUES ({version}, '{now_iso()}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return len(MIGRATIONS)


def backup_database(db_file: Path, backups_dir: Path, keep: int, label: str = "") -> Path | None:
    """Copy the DB to backups_dir with a timestamped name and prune old copies.

    Uses SQLite's online backup API so the copy is consistent. Returns the
    backup path, or None if there is no database yet.
    """
    if not Path(db_file).exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    target = backups_dir / f"{BACKUP_PREFIX}{stamp}{suffix}.db"
    n = 1
    while target.exists():
        target = backups_dir / f"{BACKUP_PREFIX}{stamp}{suffix}_{n}.db"
        n += 1
    src = sqlite3.connect(db_file)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    prune_backups(backups_dir, keep)
    return target


def prune_backups(backups_dir: Path, keep: int) -> None:
    backups = sorted(backups_dir.glob(f"{BACKUP_PREFIX}*.db"))
    for old in backups[: max(len(backups) - keep, 0)]:
        old.unlink()


def open_database(db_file: Path, backups_dir: Path, keep: int) -> sqlite3.Connection:
    """Startup sequence: back up the existing DB, connect, migrate."""
    backup_database(db_file, backups_dir, keep)
    conn = connect(db_file)
    try:
        migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn
