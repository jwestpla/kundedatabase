"""The fake sample file imports with the expected edge-case results."""

from kundedb import excel_io, repo
from tools.make_sample_xlsx import make_rows, write


def test_sample_file_imports(conn, tmp_path):
    path = write(tmp_path / "kunder_test.xlsx", make_rows(30))
    sheet = excel_io.read_sheet(path)
    assert sheet.header_row == 3 and sheet.missing == []
    s = excel_io.import_customers(conn, sheet, excel_io.MERGE)
    assert s.errors == []
    assert s.skipped == 1  # the row with only an e-mail
    customers = repo.list_customers(conn)
    by_name = {c.full_name: c for c in customers}
    assert by_name["Privat Person"].postcode == "0150" and by_name["Privat Person"].kommunenr == "0301"
    dobbel = [c for c in customers if c.company == "Dobbel Gård AS"]
    assert len(dobbel) == 1 and dobbel[0].phone == "471 23 456" and dobbel[0].address == "Fiktivvegen 9"
    text = "\n".join(s.warnings)
    assert "kontrollsiffer" in text and "9 siffer" in text and "«tolv/tre»" in text
    assert all(c.postcode is None or len(c.postcode) == 4 for c in customers)
