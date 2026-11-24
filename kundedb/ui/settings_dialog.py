"""Innstillinger: map background and the optional Google Maps API key (stored in the local database)."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import ttk

from .. import repo
from ..map_export import BACKGROUNDS
from .widgets import GREY, EditDialog


class SettingsDialog(EditDialog):
    def __init__(self, master, conn: sqlite3.Connection):
        super().__init__(master, "Innstillinger")
        self.conn = conn
        settings = repo.get_settings(conn)
        f = self.form
        self.background = tk.StringVar(value=BACKGROUNDS.get(settings.get("map_background", ""),
                                                             next(iter(BACKGROUNDS.values()))))
        f.custom("map_background", "Bakgrunnskart",
                 ttk.Combobox(f, textvariable=self.background, values=list(BACKGROUNDS.values()), state="readonly",
                              width=34))
        self.key = tk.StringVar(value=settings.get("google_maps_api_key", ""))
        key_row = ttk.Frame(f)
        self.key_entry = ttk.Entry(key_row, textvariable=self.key, width=44, show="•")
        self.key_entry.pack(side="left")
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(key_row, text="Vis", variable=self.show_key,
                        command=lambda: self.key_entry.configure(show="" if self.show_key.get() else "•")
                        ).pack(side="left", padx=(6, 0))
        f.custom("google_maps_api_key", "Google Maps API-nøkkel", key_row)
        ttk.Label(self.extra, foreground=GREY, wraplength=520, justify="left", text=(
            "Bakgrunnskartet gjelder kartet over utvalget (Leaflet). Begge kartlagene kan velges i kartet.\n\n"
            "API-nøkkel er valgfritt. Med nøkkel lages kartet med Google Maps i stedet for Leaflet. Nøkkelen "
            "skrives inn i kartfilen (HTML) som lagres i datamappen – del ikke den filen, og begrens nøkkelen "
            "til «Maps JavaScript API» med et lavt dagsforbruk i Google Cloud Console.")).pack(anchor="w")

    def save(self) -> bool | None:
        code = next((k for k, v in BACKGROUNDS.items() if v == self.background.get()), "kartverket")
        repo.save_settings(self.conn, {"map_background": code, "google_maps_api_key": self.key.get().strip()})
        return None
