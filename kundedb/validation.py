"""Cleaning and checking of customer fields. Pure (no database, no tkinter).

Checks only warn: a customer is always saved, and the warnings are shown to the advisor.
Messages are Norwegian because they are shown in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime

from .models import DATA_FIELDS, FRUITS, Customer

_ORG_NR_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def digits_only(value: str | None) -> str:
    """Strip spaces and the separators people type in numbers."""
    return re.sub(r"[\s.\-]", "", value or "")


def is_valid_org_nr(value: str | None) -> bool:
    """Brønnøysund organisation number: 9 digits, mod11 check digit."""
    digits = digits_only(value)
    if not re.fullmatch(r"\d{9}", digits):
        return False
    total = sum(int(d) * w for d, w in zip(digits[:8], _ORG_NR_WEIGHTS))
    check = 11 - total % 11
    if check == 11:
        check = 0
    if check == 10:
        return False
    return check == int(digits[8])


def is_valid_email(value: str | None) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


def is_four_digits(value: str | None) -> bool:
    return bool(re.fullmatch(r"\d{4}", (value or "").strip()))


# --- Cleaning -----------------------------------------------------------------------------------


def cell_text(value) -> str | None:
    """Text from an Excel cell or a form field. Whole numbers stored as floats lose the '.0'."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Ja" if value else "Nei"
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
    elif isinstance(value, datetime):
        text = value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat(" ", "minutes")
    elif isinstance(value, date):
        text = value.isoformat()
    else:
        text = str(value)
    text = text.strip()
    return text or None


def pad4(value: str | None) -> str | None:
    """Zero-pad a number of 1–3 digits to 4 (postnummer, kommunenr stored as numbers in Excel)."""
    if value is None:
        return None
    text = value.strip()
    return text.zfill(4) if re.fullmatch(r"\d{1,3}", text) else text


def normalize_org_nr(value: str | None) -> str | None:
    """'923 609 016' -> '923609016'. Anything that isn't digits after removing separators is kept as written."""
    if value is None:
        return None
    digits = digits_only(value)
    return digits if digits.isdigit() else value.strip()


def normalize(c: Customer) -> Customer:
    """Trim all text, pad postnummer/kommunenr, compact org.nr, and parse gnr/bnr."""
    values = {k: cell_text(getattr(c, k)) for k in DATA_FIELDS}
    values["postcode"] = pad4(values["postcode"])
    values["kommunenr"] = pad4(values["kommunenr"])
    values["org_nr"] = normalize_org_nr(values["org_nr"])
    values["fruit"] = format_fruit(*split_fruit(values["fruit"]))
    props = parse_gnr_bnr(values["gnr_bnr"])
    gnr, bnr = (props[0].gnr, props[0].bnr) if props else (None, None)
    notes = c.notes.strip() if c.notes and c.notes.strip() else None
    return replace(c, **values, gnr=gnr, bnr=bnr, notes=notes)


# --- Fruit ----------------------------------------------------------------------------------------

_FRUIT_ALIASES: dict[str, str] = {}
for _name, _words in {
    "Eple": ("eple", "epler", "eplet", "eplene", "apple", "apples"),
    "Pære": ("pære", "pærer", "pæra", "pærene", "paere", "paerer", "pear", "pears"),
    "Plomme": ("plomme", "plommer", "plomma", "plommene", "plum", "plums"),
    "Kirsebær": ("kirsebær", "kirsebaer", "morell", "moreller", "morellene", "søtkirsebær", "surkirsebær",
                 "cherry", "cherries"),
}.items():
    for _word in _words:
        _FRUIT_ALIASES[_word] = _name
_FRUIT_SPLIT = re.compile(r"[,;/+&\n]|\bog\b|\band\b", re.IGNORECASE)


def split_fruit(text: str | None) -> tuple[list[str], list[str]]:
    """(known fruit in FRUITS order, other words as written) from e.g. 'Plommer og kirsebær, eple'."""
    known: set[str] = set()
    other: list[str] = []
    for part in _FRUIT_SPLIT.split(text or ""):
        word = part.strip(" .-")
        if not word:
            continue
        name = _FRUIT_ALIASES.get(word.casefold())
        if name:
            known.add(name)
        elif word.casefold() not in {o.casefold() for o in other}:
            other.append(word)
    return [f for f in FRUITS if f in known], other


def format_fruit(known: list[str], other: list[str] = ()) -> str | None:  # type: ignore[assignment]
    return ", ".join([*known, *other]) or None


# --- Gnr / bnr ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Matrikkel:
    gnr: int
    bnr: int
    fnr: int = 0
    kommunenr: str | None = None  # when written in front, as in "4642-12/3"

    def text(self) -> str:
        base = f"{self.gnr}/{self.bnr}" + (f"/{self.fnr}" if self.fnr else "")
        return f"{self.kommunenr}-{base}" if self.kommunenr else base


_SEP = r"\s*(?:/|-|–|bnr\.?)\s*"
_MATRIKKEL_RE = re.compile(
    r"(?:(\d{4})\s*[-–]\s*(?=\d{1,5}\s*/))?"      # optional kommunenr in front: 4642-12/3
    r"(?:gnr\.?\s*)?(\d{1,5})" + _SEP + r"(\d{1,5})"  # gnr / bnr  (also "gnr 12 bnr 3")
    r"(?:\s*(?:/|-|–|fnr\.?)\s*(\d{1,5}))?",        # optional festenummer
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"[,;+&]|\bog\b", re.IGNORECASE)


def split_gnr_bnr(text: str | None) -> tuple[list[Matrikkel], list[str]]:
    """Properties found in a "Gnr og bnr" cell, and the parts that could not be read.

    Accepts "12/3", "12/3/0", "12-3", "gnr 12 bnr 3", "4642-12/3" and several separated by
    comma, semicolon or "og".
    """
    raw = (text or "").strip()
    if not raw:
        return [], []
    raw = re.sub(r",\s*(?=bnr|fnr)", " ", raw, flags=re.IGNORECASE)  # "gnr 12, bnr 3"
    found: list[Matrikkel] = []
    bad: list[str] = []
    for part in _SPLIT_RE.split(raw):
        part = part.strip()
        if not part:
            continue
        m = _MATRIKKEL_RE.search(part)
        if m is None:
            bad.append(part)
            continue
        knr, gnr, bnr, fnr = m.groups()
        found.append(Matrikkel(int(gnr), int(bnr), int(fnr or 0), knr))
    return found, bad


def parse_gnr_bnr(text: str | None) -> list[Matrikkel]:
    return split_gnr_bnr(text)[0]


# --- Warnings -----------------------------------------------------------------------------------


def warnings(c: Customer) -> list[str]:
    """Norwegian warnings for a (normalised) customer. Never blocks saving."""
    out: list[str] = []
    if not c.company and not c.full_name:
        out.append("Verken Firma eller Fullt navn er fylt ut.")
    if c.email and not is_valid_email(c.email):
        out.append(f"E-postadressen «{c.email}» ser ikke gyldig ut.")
    if c.org_nr and not is_valid_org_nr(c.org_nr):
        if re.fullmatch(r"\d{9}", digits_only(c.org_nr)):
            out.append(f"Org.nr «{c.org_nr}» har feil kontrollsiffer (mod11).")
        else:
            out.append(f"Org.nr «{c.org_nr}» skal ha 9 siffer.")
    if c.postcode and not is_four_digits(c.postcode):
        out.append(f"Postnummer «{c.postcode}» skal ha 4 siffer.")
    if c.kommunenr and not is_four_digits(c.kommunenr):
        out.append(f"Kommunenr «{c.kommunenr}» skal ha 4 siffer.")
    if c.fruit:
        _known, other = split_fruit(c.fruit)
        if other:
            out.append(f"Frukt: ukjent «{', '.join(other)}» (kjente: {', '.join(FRUITS)}). Lagret som skrevet.")
    if c.gnr_bnr:
        props, bad = split_gnr_bnr(c.gnr_bnr)
        if bad:
            out.append(f"Gnr og bnr: kunne ikke lese «{', '.join(bad)}» (skriv f.eks. 12/3 eller 12/3/0).")
        knrs = {p.kommunenr for p in props if p.kommunenr}
        if c.kommunenr and knrs - {c.kommunenr}:
            out.append(f"Gnr og bnr nevner kommunenr {', '.join(sorted(knrs))}, men Kommunenr er {c.kommunenr}.")
    return out
