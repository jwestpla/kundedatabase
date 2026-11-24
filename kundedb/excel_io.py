"""Excel (.xlsx) import and export. No tkinter.

Import: the header row is found among the first rows of the sheet and matched tolerantly (case,
spaces, punctuation). Numbers Excel stored as numbers (postnummer 430, org.nr as float) are turned
back into text, and postnummer/kommunenr are zero-padded. Export writes the same 11 headers (as
text cells, so leading zeros survive) plus coordinates and notes, which the import also reads back.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import db, repo, validation
from .models import DATA_FIELDS, FIELD_LABELS, GEOCODE_SOURCES, Customer

HEADER_SEARCH_ROWS = 10
PREVIEW_ROWS = 15
MAX_MESSAGES = 200

# Optional columns written by our own export; read back so an export can be re-imported without losses.
EXTRA_LABELS: dict[str, str] = {
    "lat": "Breddegrad",
    "lon": "Lengdegrad",
    "geocode_source": "Koordinatkilde",
    "notes": "Notater",
}

MERGE, REPLACE = "merge", "replace"


def normalize_header(text) -> str:
    """'  Telefon - Mobilnr. ' -> 'telefonmobilnr'. Letters (incl. æøå) and digits only, lower case."""
    return re.sub(r"[\W_]+", "", str(text or "").casefold())


_ALIASES: dict[str, str] = {
    **{normalize_header(label): key for key, label in FIELD_LABELS.items()},
    **{normalize_header(label): key for key, label in EXTRA_LABELS.items()},
    "firmanavn": "company", "foretak": "company", "poststed": "place", "navn": "full_name",
    "epostadresse": "email", "email": "email", "adresse": "address", "postnr": "postcode",
    "orgnummer": "org_nr", "organisasjonsnummer": "org_nr", "gnrbnr": "gnr_bnr", "kommunenummer": "kommunenr",
    "knr": "kommunenr", "telefon": "phone", "mobil": "phone", "mobilnr": "phone", "tlf": "phone",
    "lat": "lat", "lon": "lon", "notat": "notes",
    "fruktslag": "fruit", "fruktart": "fruit", "frukttype": "fruit", "fruit": "fruit", "frukter": "fruit",
}


class ExcelError(Exception):
    """The file can't be read; the message is Norwegian, for the user."""


@dataclass
class SheetData:
    sheet: str
    sheets: list[str]
    header_row: int  # 1-based row number in Excel
    columns: dict[int, str]  # 0-based column index -> field key
    headers: dict[str, str]  # field key -> header as written in the file
    unknown_headers: list[str]
    rows: list[tuple[int, dict[str, object]]]  # (Excel row number, raw cell values by field key)

    @property
    def missing(self) -> list[str]:
        return [FIELD_LABELS[k] for k in DATA_FIELDS if k not in self.headers]


def read_sheet(path: Path | str, sheet: str | None = None) -> SheetData:
    """Read one sheet (default: the first). Raises ExcelError."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency missing
        raise ExcelError("Programmet mangler pakken openpyxl (pip install openpyxl).") from exc
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parse problem means "not usable"
        raise ExcelError(f"Filen kunne ikke leses som Excel-fil (.xlsx): {exc}") from exc
    try:
        names = list(wb.sheetnames)
        ws = wb[sheet] if sheet in names else wb[names[0]]
        all_rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    best_index, best_columns = -1, {}
    for index, row in enumerate(all_rows[:HEADER_SEARCH_ROWS]):
        columns = {}
        for col, value in enumerate(row):
            key = _ALIASES.get(normalize_header(value))
            if key and key not in columns.values():
                columns[col] = key
        if len(columns) > len(best_columns):
            best_index, best_columns = index, columns
    if not any(k in DATA_FIELDS for k in best_columns.values()):
        raise ExcelError(
            "Fant ingen kjente kolonneoverskrifter i de første radene av arket «" + ws.title + "». "
            "Forventet: " + ", ".join(FIELD_LABELS.values()) + ".")
    header = all_rows[best_index]
    unknown = [str(v).strip() for i, v in enumerate(header) if i not in best_columns and v not in (None, "")]
    rows = []
    for offset, row in enumerate(all_rows[best_index + 1:], start=best_index + 2):
        values = {key: row[col] if col < len(row) else None for col, key in best_columns.items()}
        if any(validation.cell_text(v) for v in values.values()):
            rows.append((offset, values))
    return SheetData(sheet=ws.title, sheets=names, header_row=best_index + 1, columns=best_columns,
                     headers={key: str(header[col]).strip() for col, key in best_columns.items()},
                     unknown_headers=unknown, rows=rows)


def _number(value) -> float | None:
    text = validation.cell_text(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", ".").replace(" ", ""))
    except ValueError:
        raise ValueError(f"«{text}» er ikke et tall") from None


def row_to_customer(values: dict[str, object]) -> Customer:
    """A customer from raw cell values. Raises ValueError for unreadable coordinates."""
    c = Customer(**{k: validation.cell_text(values.get(k)) for k in DATA_FIELDS},
                 notes=validation.cell_text(values.get("notes")))
    lat, lon = _number(values.get("lat")), _number(values.get("lon"))
    if (lat is None) != (lon is None):
        raise ValueError("bare én av Breddegrad og Lengdegrad er fylt ut")
    if lat is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"koordinatene {lat}, {lon} er utenfor gyldig område")
        source_text = (validation.cell_text(values.get("geocode_source")) or "").casefold()
        source = next((code for code, label in GEOCODE_SOURCES.items()
                       if source_text in (code, label.casefold())), "manuell")
        c = replace(c, lat=lat, lon=lon, geocode_source=source, geocode_date=db.now_iso(),
                    geocode_note="Importert fra Excel")
    return validation.normalize(c)


@dataclass
class ImportSummary:
    mode: str
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    deleted: int = 0  # replace mode: customers removed first
    touched_ids: list[int] = field(default_factory=list)  # new or updated

    def text(self) -> str:
        lines = []
        if self.mode == REPLACE:
            lines.append(f"Slettet før import: {self.deleted}")
        lines += [
            f"Nye: {self.new}",
            f"Oppdatert: {self.updated}",
            f"Hoppet over: {self.skipped + self.unchanged}"
            + (f" ({self.unchanged} uendret, {self.skipped} uten Firma og Fullt navn)" if self.skipped else ""),
            f"Feil: {len(self.errors)}",
        ]
        if self.errors:
            lines += ["", "Feil (radene er ikke importert):", *(f"• {e}" for e in self.errors[:MAX_MESSAGES])]
        if self.warnings:
            lines += ["", f"Advarsler ({len(self.warnings)} – radene er importert):",
                      *(f"• {w}" for w in self.warnings[:MAX_MESSAGES])]
            if len(self.warnings) > MAX_MESSAGES:
                lines.append(f"… og {len(self.warnings) - MAX_MESSAGES} til.")
        return "\n".join(lines)


def _name_key(c: Customer) -> tuple[str, str] | None:
    key = tuple(" ".join((v or "").split()).casefold() for v in (c.company, c.full_name))
    return key if any(key) else None  # type: ignore[return-value]


def _merge(existing: Customer, incoming: Customer, sheet_keys: set[str]) -> Customer:
    """Values from the file replace stored values; empty cells and columns not in the file keep them."""
    changes = {k: getattr(incoming, k) for k in (*DATA_FIELDS, "notes")
               if k in sheet_keys and getattr(incoming, k) is not None}
    if incoming.has_coordinates:
        changes.update(lat=incoming.lat, lon=incoming.lon, geocode_source=incoming.geocode_source)
        if (incoming.lat, incoming.lon) != (existing.lat, existing.lon):
            changes.update(geocode_date=incoming.geocode_date, geocode_note=incoming.geocode_note)
    return replace(existing, **changes)


def import_customers(conn: sqlite3.Connection, sheet: SheetData, mode: str = MERGE) -> ImportSummary:
    """Import all rows in one transaction.

    merge: match on Org.nr, else on Firma + Fullt navn (only against customers without another
    Org.nr); matched customers are updated, others added. replace: delete everything first, then
    the same (so duplicate rows in the file become one customer).
    """
    summary = ImportSummary(mode=mode)
    sheet_keys = set(sheet.columns.values())
    with db.transaction(conn):
        if mode == REPLACE:
            summary.deleted = repo.delete_all(conn)
        by_org: dict[str, list[Customer]] = {}
        by_name: dict[tuple[str, str], list[Customer]] = {}

        def index(c: Customer) -> None:
            if c.org_nr:
                by_org.setdefault(c.org_nr, []).append(c)
            key = _name_key(c)
            if key:
                by_name.setdefault(key, []).append(c)

        def unindex(c: Customer) -> None:
            for table in (by_org, by_name):
                for items in table.values():
                    items[:] = [x for x in items if x.id != c.id]

        for c in repo.list_customers(conn):
            index(c)

        for row_no, values in sheet.rows:
            where = f"Rad {row_no}"
            try:
                incoming = row_to_customer(values)
            except ValueError as exc:
                summary.errors.append(f"{where}: {exc}.")
                continue
            if not incoming.company and not incoming.full_name:
                summary.skipped += 1
                summary.warnings.append(f"{where}: hoppet over – verken Firma eller Fullt navn er fylt ut.")
                continue
            label = f"{where} ({incoming.display_name})"

            match: Customer | None = None
            candidates = by_org.get(incoming.org_nr or "", [])
            if len(candidates) > 1:
                summary.errors.append(f"{label}: Org.nr {incoming.org_nr} finnes hos {len(candidates)} kunder "
                                      "i databasen – vet ikke hvilken som skal oppdateres.")
                continue
            if candidates:
                match = candidates[0]
            else:
                key = _name_key(incoming)
                named = [c for c in by_name.get(key, []) if not (c.org_nr and incoming.org_nr)] if key else []
                if len(named) > 1:
                    summary.errors.append(f"{label}: {len(named)} kunder i databasen har samme Firma og Fullt navn "
                                          "– vet ikke hvilken som skal oppdateres.")
                    continue
                match = named[0] if named else None

            try:
                if match is None:
                    saved = repo.save_customer(conn, incoming)
                    summary.new += 1
                else:
                    merged = validation.normalize(_merge(match, incoming, sheet_keys))
                    if repo.same_data(match, merged):
                        summary.unchanged += 1
                        continue
                    saved = repo.save_customer(conn, merged)
                    summary.updated += 1
                    unindex(match)
            except sqlite3.Error as exc:
                summary.errors.append(f"{label}: kunne ikke lagres ({exc}).")
                continue
            index(saved)
            summary.touched_ids.append(saved.id)  # type: ignore[arg-type]
            summary.warnings += [f"{label}: {w}" for w in validation.warnings(saved)]
    return summary


def export_customers(path: Path | str, customers: list[Customer], coordinates: bool = True,
                     notes: bool = True) -> Path:
    """Write customers to .xlsx: the 11 standard headers in import order, then optionally Breddegrad/Lengdegrad/
    Koordinatkilde and Notater. All but the coordinate cells are text cells, so leading zeros survive editing.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    extra = [k for k in EXTRA_LABELS if (coordinates and k in ("lat", "lon", "geocode_source"))
             or (notes and k == "notes")]
    wb = Workbook()
    ws = wb.active
    ws.title = "Kunder"
    headers = [*FIELD_LABELS.values(), *(EXTRA_LABELS[k] for k in extra)]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for c in customers:
        values = {"lat": c.lat if c.lat is not None else "", "lon": c.lon if c.lon is not None else "",
                  "geocode_source": GEOCODE_SOURCES.get(c.geocode_source or "", ""), "notes": c.notes or ""}
        ws.append([*(getattr(c, k) or "" for k in DATA_FIELDS), *(values[k] for k in extra)])
    keys = [*DATA_FIELDS, *extra]
    for col, key in enumerate(keys, start=1):
        letter = get_column_letter(col)
        width = max((len(str(cell.value or "")) for cell in ws[letter]), default=8)
        ws.column_dimensions[letter].width = min(max(width + 2, 10), 50)
        if key not in ("lat", "lon"):
            for cell in ws[letter][1:]:
                cell.number_format = "@"  # text: keeps leading zeros when edited in Excel
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    path = Path(path)
    wb.save(path)
    return path
