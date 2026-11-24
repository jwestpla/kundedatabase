"""All fields of the highlighted customer, read-only (values can be selected and copied)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..geocode import format_coordinates
from ..models import FIELD_LABELS, GEOCODE_SOURCES, OTHER_LABELS, Customer
from ..validation import warnings
from .widgets import AMBER, GREEN, GREY, RED


def _date(text: str | None) -> str:
    """'2026-11-24T10:51:00' -> '24.11.2026 10:51'."""
    if not text:
        return ""
    day, _, time = text.partition("T")
    y, m, d = (day.split("-") + ["", "", ""])[:3]
    return f"{d}.{m}.{y}" + (f" {time[:5]}" if time else "")


class DetailPanel(ttk.LabelFrame):
    def __init__(self, master, actions: dict[str, Callable[[], None]]):
        super().__init__(master, text="Kundedetaljer", padding=8)
        self.columnconfigure(1, weight=1)
        self.title_label = ttk.Label(self, text="Ingen kunde valgt.", font=("TkDefaultFont", 0, "bold"),
                                     wraplength=280, justify="left")
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        # Buttons at the top: always visible, also on small (125 %-scaled laptop) screens.
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        buttons.columnconfigure((0, 1), weight=1)
        self.buttons: list[ttk.Button] = []
        specs = [("Rediger…", "edit"), ("Vis i Google Maps", "maps"), ("Hent koordinater", "geocode"),
                 ("Slett…", "delete")]
        for i, (text, key) in enumerate(specs):
            b = ttk.Button(buttons, text=text, command=actions[key])
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else 3, 0), pady=1)
            self.buttons.append(b)
        self._vars: dict[str, tk.StringVar] = {}
        row = 2
        for key, label in [*FIELD_LABELS.items(), ("coordinates", OTHER_LABELS["coordinates"])]:
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=1)
            var = self._vars[key] = tk.StringVar()
            ttk.Entry(self, textvariable=var, state="readonly", width=30).grid(row=row, column=1, sticky="ew", pady=1)
            row += 1
        self.geo_label = ttk.Label(self, text="", wraplength=280, justify="left", foreground=GREY)
        self.geo_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 4))
        row += 1
        ttk.Label(self, text=OTHER_LABELS["notes"]).grid(row=row, column=0, sticky="nw", padx=(0, 6))
        self.notes = tk.Text(self, height=4, width=30, wrap="word", font="TkDefaultFont", state="disabled",
                             background=ttk.Style(self).lookup("TFrame", "background") or None, relief="flat")
        self.notes.grid(row=row, column=1, sticky="nsew")
        self.rowconfigure(row, weight=1)
        row += 1
        self.warn_label = ttk.Label(self, text="", wraplength=280, justify="left", foreground=AMBER)
        self.warn_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1
        self.stamp_label = ttk.Label(self, text="", foreground=GREY)
        self.stamp_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.show(None)

    def show(self, c: Customer | None) -> None:
        for b in self.buttons:
            b.state(["!disabled"] if c else ["disabled"])
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        if c is None:
            self.title_label.configure(text="Ingen kunde valgt.")
            for var in self._vars.values():
                var.set("")
            self.geo_label.configure(text="")
            self.warn_label.configure(text="")
            self.stamp_label.configure(text="")
            self.notes.configure(state="disabled")
            return
        self.title_label.configure(text=c.display_name)
        for key in FIELD_LABELS:
            self._vars[key].set(getattr(c, key) or "")
        if c.has_coordinates:
            self._vars["coordinates"].set(format_coordinates(c.lat, c.lon))  # type: ignore[arg-type]
            source = GEOCODE_SOURCES.get(c.geocode_source or "", "")
            text = f"Kilde: {source}" + (f", {_date(c.geocode_date)}" if c.geocode_date else "")
            if c.geocode_note:
                text += f"\n{c.geocode_note}"
            self.geo_label.configure(text=text, foreground=GREEN if c.geocode_source != "postnummer" else AMBER)
        else:
            self._vars["coordinates"].set("⚠ Mangler")
            if c.geocode_failed:
                text = f"{c.geocode_note or 'Ikke funnet'} ({_date(c.geocode_date)}). Rediger adressen, eller sett " \
                       "koordinatene selv i Rediger…"
            else:
                text = "Ikke slått opp ennå. Trykk «Hent koordinater»."
            self.geo_label.configure(text=text, foreground=RED)
        self.notes.insert("1.0", c.notes or "")
        self.notes.configure(state="disabled")
        w = warnings(c)
        self.warn_label.configure(text="\n".join(f"⚠ {m}" for m in w))
        self.stamp_label.configure(text=f"Opprettet {_date(c.created)} · endret {_date(c.updated)}")
