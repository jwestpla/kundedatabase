import datetime

import pytest

from kundedb.models import Customer
from kundedb.validation import (
    Matrikkel, cell_text, format_fruit, is_valid_email, is_valid_org_nr, normalize, pad4, parse_gnr_bnr, split_fruit,
    split_gnr_bnr, warnings,
)


@pytest.mark.parametrize("value, ok", [
    ("923609016", True), ("923 609 016", True), ("923609017", False), ("12345678", False), ("", False), (None, False),
])
def test_org_nr(value, ok):
    assert is_valid_org_nr(value) is ok


@pytest.mark.parametrize("value, ok", [
    ("ola@gard.no", True), (" ola@gard.no ", True), ("ola@gard", False), ("ola gard@x.no", False), ("", False),
])
def test_email(value, ok):
    assert is_valid_email(value) is ok


def test_cell_text_numbers_from_excel():
    assert cell_text(1430) == "1430"
    assert cell_text(430.0) == "430"
    assert cell_text(91234567.0) == "91234567"
    assert cell_text(59.5) == "59.5"
    assert cell_text("  x  ") == "x"
    assert cell_text("   ") is None
    assert cell_text(None) is None
    assert cell_text(datetime.datetime(2026, 1, 2)) == "2026-01-02"


def test_pad4():
    assert pad4("430") == "0430"
    assert pad4("7") == "0007"
    assert pad4("1430") == "1430"
    assert pad4("14 30") == "14 30"  # not a number: left as written (and warned about)
    assert pad4(None) is None


@pytest.mark.parametrize("text, expected", [
    ("12/3", [Matrikkel(12, 3)]),
    ("12/3/0", [Matrikkel(12, 3, 0)]),
    ("12/3/4", [Matrikkel(12, 3, 4)]),
    ("12-3", [Matrikkel(12, 3)]),
    ("12 / 3", [Matrikkel(12, 3)]),
    ("12/3, 14/1", [Matrikkel(12, 3), Matrikkel(14, 1)]),
    ("12/3; 14-1/0 og 15/2", [Matrikkel(12, 3), Matrikkel(14, 1), Matrikkel(15, 2)]),
    ("gnr 12 bnr 3", [Matrikkel(12, 3)]),
    ("Gnr. 12, bnr. 3", [Matrikkel(12, 3)]),
    ("4642-12/3", [Matrikkel(12, 3, 0, "4642")]),
    ("4642-12/3/1", [Matrikkel(12, 3, 1, "4642")]),
    ("1234-5", [Matrikkel(1234, 5)]),  # no slash after: gnr 1234 bnr 5, not a kommunenr
    ("", []),
    (None, []),
])
def test_parse_gnr_bnr(text, expected):
    assert parse_gnr_bnr(text) == expected


def test_split_gnr_bnr_reports_unreadable_parts():
    found, bad = split_gnr_bnr("12/3, ukjent")
    assert found == [Matrikkel(12, 3)]
    assert bad == ["ukjent"]


def test_normalize_pads_and_parses():
    c = normalize(Customer(company="  Testgård ", postcode="430", kommunenr="301", org_nr="923 609 016",
                           gnr_bnr="12/3, 14/1", email=" a@b.no ", notes="  "))
    assert c.company == "Testgård"
    assert c.postcode == "0430"
    assert c.kommunenr == "0301"
    assert c.org_nr == "923609016"
    assert (c.gnr, c.bnr) == (12, 3)
    assert c.gnr_bnr == "12/3, 14/1"  # original kept
    assert c.email == "a@b.no"
    assert c.notes is None


def test_warnings():
    assert warnings(normalize(Customer(company="Testgård", org_nr="923609016", postcode="0430",
                                       kommunenr="0301", email="a@b.no", gnr_bnr="12/3"))) == []
    w = warnings(normalize(Customer(org_nr="923609017", postcode="12345", kommunenr="12a", email="nope",
                                    gnr_bnr="tolv")))
    text = "\n".join(w)
    assert "Verken Firma eller Fullt navn" in text
    assert "kontrollsiffer" in text
    assert "Postnummer «12345»" in text
    assert "Kommunenr «12a»" in text
    assert "E-postadressen «nope»" in text
    assert "kunne ikke lese «tolv»" in text
    assert "9 siffer" in "\n".join(warnings(Customer(company="x", org_nr="1234")))


def test_warning_for_conflicting_kommunenr():
    w = warnings(normalize(Customer(company="x", kommunenr="4640", gnr_bnr="4642-12/3")))
    assert any("4642" in m and "4640" in m for m in w)


@pytest.mark.parametrize("text, known, other", [
    ("Eple", ["Eple"], []),
    ("eple, pære", ["Eple", "Pære"], []),
    ("Plommer og kirsebær", ["Plomme", "Kirsebær"], []),
    ("Moreller", ["Kirsebær"], []),
    ("Pære/Plomme; epler", ["Eple", "Pære", "Plomme"], []),
    ("apples and pears", ["Eple", "Pære"], []),
    ("kirsebær, Kirsebær, eple", ["Eple", "Kirsebær"], []),
    ("eple, bringebær, Bringebær", ["Eple"], ["bringebær"]),
    ("", [], []),
    (None, [], []),
])
def test_split_fruit(text, known, other):
    assert split_fruit(text) == (known, other)


def test_fruit_normalized_and_warned():
    c = normalize(Customer(company="x", fruit="plommer og EPLER"))
    assert c.fruit == "Eple, Plomme"
    assert normalize(Customer(company="x", fruit="  ")).fruit is None
    assert format_fruit([], []) is None
    assert any("ukjent «rips»" in w for w in warnings(normalize(Customer(company="x", fruit="eple, rips"))))
