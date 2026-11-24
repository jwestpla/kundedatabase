from pathlib import Path

import pytest

from kundedb import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    yield c
    c.close()


def make_xlsx(path: Path, rows: list[list], title: str = "Ark1", extra_sheets: dict[str, list[list]] | None = None):
    """Write rows (first row usually the headers) to a new .xlsx. Made-up data only."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    for name, sheet_rows in (extra_sheets or {}).items():
        extra = wb.create_sheet(name)
        for row in sheet_rows:
            extra.append(row)
    wb.save(path)
    return path


HEADERS = ["Firma", "Sted", "Kategori", "Fullt navn", "E-post", "Adresse 1", "Postnummer", "Org.nr",
           "Gnr og bnr", "Kommunenr", "Telefon - Mobilnr."]
