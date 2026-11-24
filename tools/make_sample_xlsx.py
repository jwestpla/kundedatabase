"""Write a FAKE customer list in the import format, for development and testing.

    .venv/bin/python tools/make_sample_xlsx.py [output.xlsx] [--count N]

Default output: sample/kunder_test.xlsx (gitignored). Names, e-mail addresses, phone numbers and street
addresses are invented. Postnummer/Kommunenr/Sted are real places so geocoding can be tried; gnr/bnr are
random small numbers (they may or may not match a real property, which is public matrikkel data anyway).

The file deliberately contains edge cases:
- a title and an empty row above the headers, which have odd case and spacing
- Postnummer and Kommunenr stored as NUMBERS (leading zeros lost in Excel: 150 -> 0150)
- Org.nr (synthetic, mod11-valid) and Telefon as numbers, as text with spaces, and an org.nr with a wrong check digit / 8 digits
- several properties in one cell and the formats 12/3, 12/3/0, 12-3, gnr 12 bnr 3, 4642-12/3
- empty fields, a row without Firma and Fullt navn, an invalid e-mail
- two rows for the same customer (merge on import), and a row without Firma (private person)
- Frukt written in different ways ("Plommer og kirsebær", "Pære/Plomme", "Moreller") and an unknown fruit
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kundedb.models import FIELD_LABELS  # noqa: E402

FIRST = ["Kari", "Ola", "Ingrid", "Per", "Marit", "Lars", "Sigrid", "Nils", "Astrid", "Jon", "Liv", "Knut",
         "Solveig", "Arne", "Hilde", "Odd", "Randi", "Tor", "Berit", "Eirik"]
LAST = ["Testesen", "Prøvestad", "Eksempelsen", "Fiktivdal", "Oppdiktet", "Demoberg", "Utprøvingsen",
        "Lekeby", "Narremo", "Fantasirud"]
FARM = ["Nordre", "Søndre", "Øvre", "Nedre", "Vestre", "Austre", ""]
FARM_NAME = ["Testgard", "Prøvehaug", "Demolia", "Fiktivbakken", "Eksempelvoll", "Oppdiktmo", "Liksomtun"]
SUFFIX = [" AS", " DA", " ANS", "", "", " Gårdsdrift", " Frukt og bær"]
CATEGORIES = ["Frukt", "Bær", "Grønnsaker", "Korn", "Melk", "frukt ", "Frukt og bær", ""]
STREETS = ["Testvegen", "Prøvebakken", "Demolia", "Eksempelgata", "Fiktivvegen", "Oppdiktstien"]
# (postnummer, sted, kommunenr): real places
PLACES = [("0150", "Oslo", "0301"), ("1430", "Ås", "3218"), ("6887", "Lærdal", "4642"),
          ("5780", "Kinsarvik", "4618"), ("3800", "Bø i Telemark", "4020"), ("2312", "Ottestad", "3411"),
          ("7120", "Leksvik", "5054"), ("0661", "Oslo", "0301"), ("4370", "Egersund", "1101"),
          ("8001", "Bodø", "1804"), ("0870", "Oslo", "0301"), ("3080", "Holmestrand", "3903")]
DUPLICATE_ORG = "899999991"  # synthetic, mod11-valid; only used by the deliberate duplicate rows
HEADERS = ["  FIRMA ", "sted", "Kategori", "Fullt  navn", "E-POST", "adresse 1", "Postnummer ", "Org.nr.",
           "Gnr og bnr", "kommunenr", "Telefon - Mobilnr.", "Frukt "]
FRUIT_TEXTS = ["Eple", "eple, pære", "Plommer og kirsebær", "Moreller", "Pære/Plomme", "epler", "Eple, Pære, Plomme",
               "kirsebær", "", "", "Eple, bringebær"]


def gnr_bnr(rng: random.Random, kommunenr: str) -> str:
    g, b = rng.randint(1, 250), rng.randint(1, 40)
    return rng.choice([
        f"{g}/{b}", f"{g}/{b}/0", f"{g}-{b}", f"gnr {g} bnr {b}",
        f"{g}/{b}, {g + 1}/{rng.randint(1, 20)}", f"{kommunenr}-{g}/{b}", "", "",
    ])


def phone(rng: random.Random):
    number = f"{rng.choice('49')}{rng.randint(1000000, 9999999)}"
    return rng.choice([int(number), number, f"{number[:3]} {number[3:5]} {number[5:]}", f"+47 {number}", None])


def synthetic_org_nr(rng: random.Random) -> str:
    """A random 9-digit number starting with 8 with a valid mod11 check digit (not a known organisation)."""
    while True:
        digits = "8" + "".join(str(rng.randint(0, 9)) for _ in range(7))
        check = 11 - sum(int(d) * w for d, w in zip(digits, (3, 2, 7, 6, 5, 4, 3, 2))) % 11
        if check == 11:
            check = 0
        if check != 10 and digits + str(check) != DUPLICATE_ORG:
            return digits + str(check)


def org_nr(rng: random.Random):
    number = synthetic_org_nr(rng)
    return rng.choice([int(number), number, f"{number[:3]} {number[3:6]} {number[6:]}", None, None])


def make_rows(count: int, seed: int = 42) -> list[list]:
    rng = random.Random(seed)
    rows = []
    used_org: set[str] = set()
    for i in range(count):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        postcode, place, knr = rng.choice(PLACES)
        company = f"{rng.choice(FARM)} {rng.choice(FARM_NAME)}{rng.choice(SUFFIX)}".strip()
        org = org_nr(rng)
        key = str(org).replace(" ", "") if org else None
        if key in used_org:  # keep Org.nr unique apart from the deliberate duplicate below
            org = None
        elif key:
            used_org.add(key)
        rows.append([
            company if rng.random() > 0.1 else "",
            place,
            rng.choice(CATEGORIES),
            f"{first} {last}",
            f"{first.lower()}.{last.lower()}@example.com".replace("ø", "o").replace("æ", "ae").replace("å", "a"),
            f"{rng.choice(STREETS)} {rng.randint(1, 120)}" if rng.random() > 0.15 else "",
            int(postcode) if rng.random() < 0.5 else postcode,  # number: leading zero lost
            org,
            gnr_bnr(rng, knr),
            int(knr) if rng.random() < 0.5 else knr,
            phone(rng),
            rng.choice(FRUIT_TEXTS),
        ])
    # Deliberate edge cases
    rows += [
        ["Feilnummer AS", "Ås", "Bær", "Ole Feilsen", "ole@example.com", "Testvegen 1", 1430, "899999990",
         "12/3", 3218, 91234567],  # wrong mod11 check digit
        ["Kortnummer DA", "Lærdal", "Frukt", "Kari Kortsen", "kari@example", "", "6887", "12345678",
         "4642-17/2/0", "4642", ""],  # 8-digit org.nr, invalid e-mail
        ["", "Oslo", "Grønnsaker", "Privat Person", "", "Eksempelgata 5", 150, None, "", 301, "912 34 567"],
        ["", "", "", "", "kun@epost.no", "", None, None, "", None, None],  # no Firma / Fullt navn: skipped
        ["Dobbel Gård AS", "Bodø", "Melk", "Per Dobbel", "per@example.com", "Fiktivvegen 9", 8001, int(DUPLICATE_ORG),
         "45/6, 45/7; 46/1 og 47/2", 1804, 47123456],
        ["Dobbel Gård AS", "Bodø", "Melk", "Per Dobbel", "", "", None, DUPLICATE_ORG, "", None,
         "471 23 456"],  # same Org.nr: merges into the row above
        ["Ugyldig Gnr", "Ottestad", "Korn", "Lars Rar", "lars@example.com", "", "2312", None, "tolv/tre", "3411",
         None],  # unreadable gnr/bnr
        ["Tom Rad Nesten", None, None, None, None, None, None, None, None, None, None],
    ]
    return rows


def write(path: Path, rows: list[list]) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Kunder"
    ws.append(["Kundeliste (TESTDATA – oppdiktede personer)"])
    ws.append([])
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Lag en testfil med oppdiktede kunder.")
    parser.add_argument("output", nargs="?", default=str(ROOT / "sample" / "kunder_test.xlsx"))
    parser.add_argument("--count", type=int, default=150)
    args = parser.parse_args()
    assert len(HEADERS) == len(FIELD_LABELS)
    path = write(Path(args.output), make_rows(args.count))
    print(f"Skrev {path} ({args.count} + 8 testrader)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
