"""The customer record and the Norwegian names of its fields."""

from __future__ import annotations

from dataclasses import dataclass, fields

# The data fields in Excel column order. The labels are the exact Excel headers and the UI labels.
FIELD_LABELS: dict[str, str] = {
    "company": "Firma",
    "place": "Sted",
    "category": "Kategori",
    "full_name": "Fullt navn",
    "email": "E-post",
    "address": "Adresse 1",
    "postcode": "Postnummer",
    "org_nr": "Org.nr",
    "gnr_bnr": "Gnr og bnr",
    "kommunenr": "Kommunenr",
    "phone": "Telefon - Mobilnr.",
}
DATA_FIELDS: tuple[str, ...] = tuple(FIELD_LABELS)

# A change in any of these means stored (looked-up) coordinates may be wrong.
ADDRESS_FIELDS: tuple[str, ...] = ("address", "postcode", "place", "kommunenr", "gnr_bnr")

GEOCODE_SOURCES: dict[str, str] = {
    "gnr_bnr": "Gnr/bnr",
    "adresse": "Adresse",
    "postnummer": "Postnummer/sted",
    "manuell": "Manuell",
}

OTHER_LABELS: dict[str, str] = {
    "notes": "Notater",
    "coordinates": "Koordinater",
    "geocode_source": "Koordinatkilde",
    "geocode_date": "Koordinater hentet",
    "geocode_note": "Kartoppslag",
    "created": "Opprettet",
    "updated": "Endret",
}


@dataclass
class Customer:
    id: int | None = None
    company: str | None = None
    place: str | None = None
    category: str | None = None
    full_name: str | None = None
    email: str | None = None
    address: str | None = None
    postcode: str | None = None
    org_nr: str | None = None
    gnr_bnr: str | None = None
    kommunenr: str | None = None
    phone: str | None = None
    gnr: int | None = None
    bnr: int | None = None
    lat: float | None = None
    lon: float | None = None
    geocode_source: str | None = None
    geocode_date: str | None = None
    geocode_note: str | None = None
    notes: str | None = None
    created: str | None = None
    updated: str | None = None

    @property
    def display_name(self) -> str:
        if self.company and self.full_name:
            return f"{self.company} ({self.full_name})"
        return self.company or self.full_name or (f"Kunde {self.id}" if self.id else "Ny kunde")

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def geocode_failed(self) -> bool:
        """Looked up for the current address without a result."""
        return not self.has_coordinates and self.geocode_date is not None

    def address_key(self) -> tuple[str, ...]:
        return tuple(" ".join((getattr(self, k) or "").split()).casefold() for k in ADDRESS_FIELDS)

    def data(self) -> dict[str, str | None]:
        return {k: getattr(self, k) for k in DATA_FIELDS}


COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(Customer) if f.name != "id")
