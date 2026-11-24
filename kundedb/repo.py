"""All SQL. Customers are cleaned with validation.normalize before they are stored."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Iterable

from . import db, validation
from .models import COLUMNS, DATA_FIELDS, Customer

_WRITABLE = tuple(c for c in COLUMNS if c not in ("created", "updated"))


def _customer(row: sqlite3.Row) -> Customer:
    return Customer(**{k: row[k] for k in row.keys()})


def list_customers(conn: sqlite3.Connection) -> list[Customer]:
    rows = conn.execute(
        "SELECT * FROM customer ORDER BY coalesce(company, full_name, '') COLLATE NOCASE, full_name COLLATE NOCASE, id"
    ).fetchall()
    return [_customer(r) for r in rows]


def get_customer(conn: sqlite3.Connection, customer_id: int) -> Customer | None:
    row = conn.execute("SELECT * FROM customer WHERE id = ?", (customer_id,)).fetchone()
    return _customer(row) if row else None


def count_customers(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]


def categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT category FROM customer WHERE trim(coalesce(category, '')) <> ''")
    return sorted({r[0].strip() for r in rows}, key=str.casefold)


def same_data(a: Customer, b: Customer) -> bool:
    """Equal in everything the advisor can edit (data fields, notes, coordinates)."""
    keys = (*DATA_FIELDS, "notes", "lat", "lon", "geocode_source")
    return all(getattr(a, k) == getattr(b, k) for k in keys)


def save_customer(conn: sqlite3.Connection, c: Customer, now: str | None = None) -> Customer:
    """Insert (id None) or update a customer and return the stored record.

    When an address field changes, coordinates that were looked up automatically are cleared so the
    customer is looked up again; coordinates entered by hand ('manuell') are kept. Coordinates the
    caller changed in the same save are kept as given.
    """
    now = now or db.now_iso()
    c = validation.normalize(c)
    if c.id is None:
        values = [getattr(c, k) for k in _WRITABLE]
        cur = conn.execute(
            f"INSERT INTO customer ({', '.join(_WRITABLE)}, created, updated) "
            f"VALUES ({', '.join('?' * len(_WRITABLE))}, ?, ?)",
            (*values, now, now),
        )
        return get_customer(conn, cur.lastrowid)  # type: ignore[return-value]

    old = get_customer(conn, c.id)
    if old is None:
        raise LookupError(f"Kunde {c.id} finnes ikke lenger.")
    if old.address_key() != c.address_key():
        untouched = (c.lat, c.lon, c.geocode_source) == (old.lat, old.lon, old.geocode_source)
        if untouched and c.geocode_source != "manuell":
            c = replace(c, lat=None, lon=None, geocode_source=None, geocode_date=None, geocode_note=None)
    if same_data(old, c) and (c.geocode_date, c.geocode_note) == (old.geocode_date, old.geocode_note):
        return old
    assignments = ", ".join(f"{k} = ?" for k in _WRITABLE)
    conn.execute(f"UPDATE customer SET {assignments}, updated = ? WHERE id = ?",
                 (*(getattr(c, k) for k in _WRITABLE), now, c.id))
    return get_customer(conn, c.id)  # type: ignore[return-value]


def save_geocode(conn: sqlite3.Connection, customer_id: int, address_key: tuple[str, ...],
                 lat: float | None, lon: float | None, source: str | None, note: str,
                 when: str | None = None, replace_manual: bool = False) -> bool:
    """Store a lookup result (lat/lon None = not found). Does not touch `updated`.

    Not stored (returns False) when the customer was deleted or its address changed while the lookup ran,
    when it has manual coordinates (unless `replace_manual`), and when nothing was found but the customer
    already has coordinates (they are kept).
    """
    current = get_customer(conn, customer_id)
    if current is None or current.address_key() != address_key:
        return False
    if current.geocode_source == "manuell" and not replace_manual:
        return False
    if lat is None and current.has_coordinates:
        return False
    conn.execute(
        "UPDATE customer SET lat = ?, lon = ?, geocode_source = ?, geocode_date = ?, geocode_note = ? WHERE id = ?",
        (lat, lon, source if lat is not None else None, when or db.now_iso(), note, customer_id),
    )
    return True


def delete_customers(conn: sqlite3.Connection, ids: Iterable[int]) -> int:
    ids = list(ids)
    with db.transaction(conn):
        for i in ids:
            conn.execute("DELETE FROM customer WHERE id = ?", (i,))
    return len(ids)


def delete_all(conn: sqlite3.Connection) -> int:
    """Only used inside an import transaction ('Erstatt alle')."""
    return conn.execute("DELETE FROM customer").rowcount


# --- Settings ---------------------------------------------------------------------------------------


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] or "" for r in conn.execute("SELECT key, value FROM setting")}


def save_settings(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    with db.transaction(conn):
        for key, value in values.items():
            conn.execute("INSERT INTO setting (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
