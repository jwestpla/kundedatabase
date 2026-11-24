import pytest

from kundedb import excel_io, repo
from kundedb.excel_io import MERGE, REPLACE, ExcelError, import_customers, read_sheet
from kundedb.models import Customer

from .conftest import HEADERS, OLD_HEADERS, make_xlsx

ROW_A = ["Testgård AS", "Ås", "Frukt", "Kari Nordmann", "kari@example.com", "Gardsvegen 1", 1430, 923609016,
         "12/3", 3218, 91234567]
ROW_B = ["", "Oslo", "Bær", "Ola Nordmann", "ola@example", "Bakken 2", 150.0, None, "12-3, 14/1", 301.0,
         "+47 912 34 568"]


def test_read_sheet_converts_numbers_and_pads(tmp_path):
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ROW_A, ROW_B]))
    assert sheet.header_row == 1
    assert sheet.missing == []
    c = excel_io.row_to_customer(sheet.rows[1][1])
    assert c.postcode == "0150"
    assert c.kommunenr == "0301"
    assert c.org_nr is None
    assert c.phone == "+47 912 34 568"
    assert (c.gnr, c.bnr) == (12, 3)
    a = excel_io.row_to_customer(sheet.rows[0][1])
    assert a.org_nr == "923609016" and a.phone == "91234567" and a.postcode == "1430"


def test_tolerant_headers_on_a_later_row(tmp_path):
    headers = ["  FIRMA ", "sted", "Kategori", "fullt  navn", "E-POST", "adresse 1", "Postnummer ", "Org.nr.",
               "Gnr og bnr", "kommunenr", "Telefon-mobilnr", " frukt", "Egen kolonne"]
    path = make_xlsx(tmp_path / "k.xlsx", [["Kundeliste 2026"], [], headers, [*ROW_A, "eple", "x"]])
    sheet = read_sheet(path)
    assert sheet.header_row == 3
    assert sheet.missing == []
    assert sheet.unknown_headers == ["Egen kolonne"]
    assert read_sheet(make_xlsx(tmp_path / "old.xlsx", [OLD_HEADERS, ROW_A])).missing == ["Frukt"]
    assert sheet.rows[0][0] == 4  # Excel row number


def test_missing_columns_and_other_sheet(tmp_path):
    path = make_xlsx(tmp_path / "k.xlsx", [["Hei"]], extra_sheets={"Kunder": [["Firma", "Postnr"], ["A", 7]]})
    with pytest.raises(ExcelError):
        read_sheet(path)
    sheet = read_sheet(path, "Kunder")
    assert sheet.sheets == ["Ark1", "Kunder"]
    assert "Fullt navn" in sheet.missing
    assert excel_io.row_to_customer(sheet.rows[0][1]).postcode == "0007"


def test_not_an_excel_file(tmp_path):
    bad = tmp_path / "x.xlsx"
    bad.write_text("not excel")
    with pytest.raises(ExcelError):
        read_sheet(bad)


def test_merge_by_org_nr_then_name(conn, tmp_path):
    repo.save_customer(conn, Customer(company="Testgård AS", full_name="Gammel Kontakt", org_nr="923609016",
                                      notes="viktig"))
    repo.save_customer(conn, Customer(full_name="Ola Nordmann", place="Oslo", phone="1"))
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ROW_A, ROW_B, ["Ny AS", "", "", "Per"]]))
    s = import_customers(conn, sheet, MERGE)
    assert (s.new, s.updated, s.unchanged, s.skipped, s.errors) == (1, 2, 0, 0, [])
    customers = {c.company or c.full_name: c for c in repo.list_customers(conn)}
    assert len(customers) == 3
    a = customers["Testgård AS"]
    assert a.full_name == "Kari Nordmann" and a.notes == "viktig"  # notes column not in file: kept
    assert customers["Ola Nordmann"].phone == "+47 912 34 568"
    assert any("ola@example" in w for w in s.warnings)

    again = import_customers(conn, sheet, MERGE)
    assert (again.new, again.updated, again.unchanged) == (0, 0, 3)


def test_empty_cells_do_not_erase(conn, tmp_path):
    repo.save_customer(conn, Customer(company="A", full_name="B", phone="123"))
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ["A", "Ås", "", "B", "", "", "", "", "", "", "", ""]]))
    s = import_customers(conn, sheet, MERGE)
    assert s.updated == 1
    c = repo.list_customers(conn)[0]
    assert c.phone == "123" and c.place == "Ås"


def test_name_match_does_not_cross_different_org_nr(conn, tmp_path):
    repo.save_customer(conn, Customer(company="Testgård AS", full_name="Kari Nordmann", org_nr="974760673"))
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ROW_A]))
    s = import_customers(conn, sheet, MERGE)
    assert s.new == 1 and repo.count_customers(conn) == 2


def test_duplicate_rows_in_file_merge_and_skips(conn, tmp_path):
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ROW_A, ROW_A, ["", "Bare sted"]]))
    s = import_customers(conn, sheet, MERGE)
    assert (s.new, s.unchanged, s.skipped) == (1, 1, 1)


def test_ambiguous_match_is_an_error(conn, tmp_path):
    repo.save_customer(conn, Customer(full_name="Ola Nordmann", place="x"))
    repo.save_customer(conn, Customer(full_name="Ola Nordmann", place="y"))
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ROW_B]))
    s = import_customers(conn, sheet, MERGE)
    assert len(s.errors) == 1 and "samme Firma og Fullt navn" in s.errors[0]


def test_replace(conn, tmp_path):
    repo.save_customer(conn, Customer(company="Gammel"))
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [HEADERS, ROW_A, ROW_B]))
    s = import_customers(conn, sheet, REPLACE)
    assert (s.deleted, s.new) == (1, 2)
    assert "Gammel" not in {c.company for c in repo.list_customers(conn)}
    assert "Slettet før import: 1" in s.text()


def test_bad_coordinates_are_errors(conn, tmp_path):
    sheet = read_sheet(make_xlsx(tmp_path / "k.xlsx", [["Firma", "Breddegrad", "Lengdegrad"], ["A", "59,6", ""],
                                                        ["B", "abc", "10"], ["C", "59,6", "10,7"]]))
    s = import_customers(conn, sheet, MERGE)
    assert s.new == 1 and len(s.errors) == 2
    c = repo.list_customers(conn)[0]
    assert (c.lat, c.lon, c.geocode_source) == (59.6, 10.7, "manuell")


def test_export_round_trip(conn, tmp_path):
    a = repo.save_customer(conn, Customer(company="A", postcode="0150", kommunenr="0301", org_nr="923609016",
                                          notes="notat"))
    repo.save_geocode(conn, a.id, a.address_key(), 59.9, 10.75, "gnr_bnr", "x")
    path = excel_io.export_customers(tmp_path / "ut.xlsx", repo.list_customers(conn))
    sheet = read_sheet(path)
    c = excel_io.row_to_customer(sheet.rows[0][1])
    assert (c.postcode, c.kommunenr, c.org_nr, c.notes) == ("0150", "0301", "923609016", "notat")
    assert (c.lat, c.lon, c.geocode_source) == (59.9, 10.75, "gnr_bnr")
    s = import_customers(conn, sheet, MERGE)
    assert (s.new, s.updated, s.unchanged) == (0, 0, 1)


def test_export_options_and_text_cells(conn, tmp_path):
    from openpyxl import load_workbook

    repo.save_customer(conn, Customer(company="A", postcode="0150", kommunenr="0301", org_nr="923609016",
                                      phone="04712345", notes="n", fruit="Eple", lat=59.9, lon=10.7, geocode_source="manuell"))
    customers = repo.list_customers(conn)
    path = excel_io.export_customers(tmp_path / "a.xlsx", customers, coordinates=False, notes=False)
    ws = load_workbook(path).active
    assert [c.value for c in ws[1]] == HEADERS
    assert ws[1][0].font.bold and ws.auto_filter.ref == "A1:L2"
    row = {h: c for h, c in zip(HEADERS, ws[2])}
    for header in ("Postnummer", "Kommunenr", "Org.nr", "Telefon - Mobilnr.", "Frukt"):
        assert row[header].number_format == "@" and isinstance(row[header].value, str)
    assert row["Postnummer"].value == "0150" and row["Telefon - Mobilnr."].value == "04712345"
    ws = load_workbook(excel_io.export_customers(tmp_path / "b.xlsx", customers, coordinates=True, notes=False)).active
    assert [c.value for c in ws[1]][12:] == ["Breddegrad", "Lengdegrad", "Koordinatkilde"]
    assert ws["M2"].value == 59.9


def test_fruit_column_import_merge_and_export(conn, tmp_path):
    rows = [HEADERS, [*ROW_A, "Plommer og kirsebær, EPLE"], [*ROW_B, "moreller / bringebær"]]
    s = import_customers(conn, read_sheet(make_xlsx(tmp_path / "k.xlsx", rows)), MERGE)
    assert s.new == 2
    by_name = {c.full_name: c for c in repo.list_customers(conn)}
    assert by_name["Kari Nordmann"].fruit == "Eple, Plomme, Kirsebær"
    assert by_name["Ola Nordmann"].fruit == "Kirsebær, bringebær"
    assert any("ukjent «bringebær»" in w for w in s.warnings)
    # an old 11-column file does not touch the stored fruit
    again = import_customers(conn, read_sheet(make_xlsx(tmp_path / "old.xlsx", [OLD_HEADERS, ROW_A])), MERGE)
    assert again.unchanged == 1
    assert repo.get_customer(conn, by_name["Kari Nordmann"].id).fruit == "Eple, Plomme, Kirsebær"
    # the file's value wins when the column is there
    import_customers(conn, read_sheet(make_xlsx(tmp_path / "k2.xlsx", [HEADERS, [*ROW_A, "pære"]])), MERGE)
    assert repo.get_customer(conn, by_name["Kari Nordmann"].id).fruit == "Pære"
    path = excel_io.export_customers(tmp_path / "ut.xlsx", repo.list_customers(conn), coordinates=False, notes=False)
    sheet = read_sheet(path)
    assert sheet.missing == [] and list(sheet.headers.values())[-1] == "Frukt"
