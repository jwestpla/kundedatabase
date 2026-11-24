"""Export to Excel: which customers (☑ / current list / all) and which extra columns."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import excel_io
from .widgets import GREY, grab, open_path, show_errors

if TYPE_CHECKING:
    from .main_window import MainWindow

CHECKED, VISIBLE, ALL = "checked", "visible", "all"
FILE_LABEL = {CHECKED: "Kunder_valgte", VISIBLE: "Kunder_utvalg", ALL: "Kunder"}


class ExportDialog(tk.Toplevel):
    def __init__(self, app: MainWindow, default: str | None = None):
        super().__init__(app)
        self.app = app
        self.title("Eksporter til Excel")
        self.transient(app)
        self.resizable(False, False)
        self.groups = {CHECKED: app.checked_customers(), VISIBLE: list(app.list.customers), ALL: list(app.customers)}

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        box = ttk.LabelFrame(body, text="Hvilke kunder?", padding=8)
        box.pack(fill="x")
        if default is None:
            default = CHECKED if self.groups[CHECKED] else VISIBLE
        self.which = tk.StringVar(value=default)
        labels = {CHECKED: "Valgte (☑)", VISIBLE: "Kundene som vises i listen nå (søk og filter)", ALL: "Alle kunder"}
        for key, label in labels.items():
            n = len(self.groups[key])
            b = ttk.Radiobutton(box, text=f"{label} – {n}", variable=self.which, value=key)
            b.pack(anchor="w", pady=1)
            if not n:
                b.state(["disabled"])

        cols = ttk.LabelFrame(body, text="Kolonner", padding=8)
        cols.pack(fill="x", pady=(10, 0))
        ttk.Label(cols, text="De 11 vanlige kolonnene (samme som ved import) kommer alltid først.",
                  foreground=GREY).pack(anchor="w")
        self.coordinates = tk.BooleanVar(value=True)
        self.notes = tk.BooleanVar(value=True)
        ttk.Checkbutton(cols, text="Ta med koordinater (Breddegrad, Lengdegrad, Koordinatkilde)",
                        variable=self.coordinates).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(cols, text="Ta med notater", variable=self.notes).pack(anchor="w")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Avbryt", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Eksporter…", command=self.export).pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.geometry(f"+{app.winfo_rootx() + 160}+{app.winfo_rooty() + 100}")
        grab(self)

    def export(self) -> None:
        which = self.which.get()
        customers = self.groups[which]
        if not customers:
            messagebox.showinfo("Eksporter", "Ingen kunder å eksportere.", parent=self)
            return
        paths = self.app.paths
        paths.export_dir.mkdir(parents=True, exist_ok=True)
        name = filedialog.asksaveasfilename(
            parent=self, title="Eksporter til Excel", defaultextension=".xlsx", filetypes=[("Excel-filer", "*.xlsx")],
            initialdir=str(paths.export_dir), initialfile=f"{FILE_LABEL[which]}_{date.today().isoformat()}.xlsx")
        if not name:
            return
        try:
            path = excel_io.export_customers(name, sorted(customers, key=lambda c: c.display_name.casefold()),
                                             coordinates=self.coordinates.get(), notes=self.notes.get())
        except OSError as exc:
            show_errors(self, [f"Kunne ikke skrive filen (er den åpen i Excel?):\n{exc}"], "Eksport feilet")
            return
        self.destroy()
        self.app.set_status(f"Eksporterte {len(customers)} kunde(r) til {path.name}.")
        if messagebox.askyesno("Eksport ferdig", f"{len(customers)} kunde(r) lagret i\n{path}\n\nÅpne filen nå?",
                               parent=self.app):
            open_path(path)
