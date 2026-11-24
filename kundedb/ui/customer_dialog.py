"""Add or edit one customer. Warnings are shown live; they never stop saving."""

from __future__ import annotations

import sqlite3
import tkinter as tk
import webbrowser
from dataclasses import replace
from tkinter import ttk

from .. import db, repo, validation
from ..geocode import address_query, format_coordinates, google_maps_url, outside_norway, parse_coordinates, parse_number
from ..models import FIELD_LABELS, OTHER_LABELS, Customer
from .widgets import AMBER, GREEN, GREY, RED, EditDialog, show_errors

COORD_HINT = ("Høyreklikk stedet i Google Maps og klikk på tallene øverst i menyen – da kopieres de. "
              "Trykk så «Lim inn koordinater».")


def _coord_text(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}".replace(".", ",")


class CustomerDialog(EditDialog):
    def __init__(self, master, conn: sqlite3.Connection, customer: Customer | None = None):
        self.conn = conn
        self.original = customer or Customer()
        super().__init__(master, "Rediger kunde" if customer else "Ny kunde", columns=2)
        self.result: Customer | None = None
        f = self.form
        L = FIELD_LABELS
        f.entry("company", L["company"], width=32)
        f.entry("full_name", L["full_name"], width=32)
        f.combo("category", L["category"], repo.categories(conn), width=30, readonly=False)
        f.entry("phone", L["phone"], width=20)
        f.entry("email", L["email"], width=32)
        f.entry("org_nr", L["org_nr"], width=14)
        f.entry("address", L["address"], width=30, column=1)
        f.entry("postcode", L["postcode"], width=8, column=1)
        f.entry("place", L["place"], width=24, column=1)
        f.entry("kommunenr", L["kommunenr"], width=8, column=1)
        f.entry("gnr_bnr", L["gnr_bnr"], width=24, column=1)
        f.custom("gnr_hint", "", ttk.Label(f, text="F.eks. 12/3, 12/3/0 eller flere: 12/3, 14/1", foreground=GREY),
                 column=1)
        coords = ttk.Frame(f)
        for key, caption in (("lat", "Bredde"), ("lon", "Lengde")):
            ttk.Label(coords, text=caption).pack(side="left", padx=(0 if key == "lat" else 10, 4))
            var = tk.StringVar(self)
            entry = ttk.Entry(coords, textvariable=var, width=12)
            entry.pack(side="left")
            f.add_var(key, entry, var)
        f.custom("coords", OTHER_LABELS["coordinates"], coords, column=1)
        buttons = ttk.Frame(f)
        ttk.Button(buttons, text="Lim inn koordinater", command=self.paste_coordinates).pack(side="left")
        ttk.Button(buttons, text="Åpne Google Maps", command=self.open_map).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Tøm", command=self.clear_coordinates).pack(side="left", padx=(6, 0))
        f.custom("coord_buttons", "", buttons, column=1)
        self.coord_status = ttk.Label(f, text=COORD_HINT, wraplength=320, justify="left", foreground=GREY)
        f.custom("coord_status", "", self.coord_status, column=1)
        for key in ("lat", "lon"):
            f.widgets[key].bind("<<Paste>>", lambda _e: self.paste_coordinates(quiet=True))

        ttk.Label(self.extra, text=OTHER_LABELS["notes"]).pack(anchor="w")
        self.notes = tk.Text(self.extra, height=4, width=90, wrap="word", font="TkDefaultFont")
        self.notes.pack(fill="x")
        f.add_text("notes", self.notes)
        self.warn_label = ttk.Label(self.extra, text="", foreground=AMBER, wraplength=720, justify="left")
        self.warn_label.pack(anchor="w", pady=(6, 0))

        c = self.original
        for key in FIELD_LABELS:
            f.set(key, getattr(c, key))
        f.set("notes", c.notes)
        f.set("lat", _coord_text(c.lat))
        f.set("lon", _coord_text(c.lon))
        for key in FIELD_LABELS:
            f.var(key).trace_add("write", lambda *_: self._update_warnings())
        self._update_warnings()
        f.widgets["company"].focus_set()

    # --- Helpers ----------------------------------------------------------------

    def _collected(self) -> Customer:
        values = {key: self.form.get(key) for key in FIELD_LABELS}
        return replace(self.original, **values, notes=self.form.get("notes"))

    def _update_warnings(self) -> None:
        w = validation.warnings(validation.normalize(self._collected()))
        self.warn_label.configure(text="\n".join(f"⚠ {m}" for m in w) + ("\n(Advarslene hindrer ikke lagring.)" if w else ""))

    def paste_coordinates(self, quiet: bool = False) -> str | None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        coords = parse_coordinates(text)
        if coords is None:
            if not quiet:
                self.coord_status.configure(text="Fant ingen koordinater på utklippstavlen. " + COORD_HINT,
                                            foreground=RED)
            return None
        lat, lon = round(coords[0], 6), round(coords[1], 6)
        self.form.set("lat", _coord_text(lat))
        self.form.set("lon", _coord_text(lon))
        note = " – merk: punktet ligger utenfor Norge. Er bredde og lengde byttet om?" if outside_norway(lat, lon) else ""
        self.coord_status.configure(text=f"Satt: {format_coordinates(lat, lon)}{note}",
                                    foreground=AMBER if note else GREEN)
        return "break"

    def clear_coordinates(self) -> None:
        self.form.set("lat", "")
        self.form.set("lon", "")
        self.coord_status.configure(text="Koordinatene fjernes når du lagrer. " + COORD_HINT, foreground=GREY)

    def open_map(self) -> None:
        c = self._collected()
        try:
            lat, lon = parse_number(self.form.get("lat")), parse_number(self.form.get("lon"))
        except ValueError:
            lat = lon = None
        if lat is not None and lon is not None:
            c = replace(c, lat=lat, lon=lon)
        else:
            c = replace(c, lat=None, lon=None)
        url = google_maps_url(validation.normalize(c)) if (c.lat is not None or address_query(c)) else None
        webbrowser.open(url or "https://www.google.com/maps")

    # --- Save -------------------------------------------------------------------

    def save(self) -> bool | None:
        c = self._collected()
        errors = []
        try:
            lat, lon = parse_number(self.form.get("lat")), parse_number(self.form.get("lon"))
        except ValueError:
            errors.append("Breddegrad og Lengdegrad må være tall (f.eks. 59,66194).")
            lat = lon = None
        if not errors and (lat is None) != (lon is None):
            errors.append("Fyll ut både Breddegrad og Lengdegrad, eller ingen av dem.")
        if not errors and lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):  # type: ignore[operator]
            errors.append("Koordinatene er utenfor gyldig område (breddegrad −90…90, lengdegrad −180…180).")
        if errors:
            show_errors(self, errors)
            return False
        lat = round(lat, 6) if lat is not None else None
        lon = round(lon, 6) if lon is not None else None
        o = self.original
        same_point = (_coord_text(lat), _coord_text(lon)) == (_coord_text(o.lat), _coord_text(o.lon))
        if lat is None:
            if o.has_coordinates:
                c = replace(c, lat=None, lon=None, geocode_source=None, geocode_date=None, geocode_note=None)
        elif not same_point:
            c = replace(c, lat=lat, lon=lon, geocode_source="manuell", geocode_date=db.now_iso(),
                        geocode_note="Satt manuelt")
        try:
            self.result = repo.save_customer(self.conn, c)
        except (sqlite3.Error, LookupError) as exc:
            show_errors(self, [f"Kunne ikke lagre: {exc}"])
            return False
        return None
