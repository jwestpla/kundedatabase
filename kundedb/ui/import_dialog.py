"""Import from Excel: pick a file, preview the first rows, choose merge or replace, show a summary."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import config, db, excel_io, validation
from ..excel_io import MERGE, PREVIEW_ROWS, REPLACE, ExcelError, SheetData
from ..models import FIELD_LABELS
from .widgets import AMBER, GREY, RED, configure_columns, show_report

if TYPE_CHECKING:
    from .main_window import MainWindow

FILETYPES = [("Excel-filer", "*.xlsx *.xlsm"), ("Alle filer", "*.*")]


class ImportDialog(tk.Toplevel):
    def __init__(self, app: MainWindow, path: Path | None = None):
        super().__init__(app)
        self.app = app
        self.title("Importer fra Excel")
        self.transient(app)
        self.path: Path | None = None
        self.sheet: SheetData | None = None
        self.summary: excel_io.ImportSummary | None = None

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        top = ttk.Frame(body)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Button(top, text="Velg fil…", command=self.choose_file).grid(row=0, column=0, sticky="w")
        self.file_label = ttk.Label(top, text="Ingen fil valgt.", foreground=GREY)
        self.file_label.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(top, text="Ark").grid(row=0, column=2, sticky="e")
        self.sheet_var = tk.StringVar()
        self.sheet_combo = ttk.Combobox(top, textvariable=self.sheet_var, state="disabled", width=20)
        self.sheet_combo.grid(row=0, column=3, sticky="e", padx=(6, 0))
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda _e: self.load(self.sheet_var.get()))

        self.info = ttk.Label(body, text="", wraplength=820, justify="left")
        self.info.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        ttk.Label(body, text=f"Forhåndsvisning (de første {PREVIEW_ROWS} radene):").grid(row=2, column=0, sticky="w")

        frame = ttk.Frame(body)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.preview = ttk.Treeview(frame, show="headings", height=PREVIEW_ROWS // 2 + 2)
        self.preview.grid(row=0, column=0, sticky="nsew")
        xs = ttk.Scrollbar(frame, orient="horizontal", command=self.preview.xview)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.preview.yview)
        self.preview.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        xs.grid(row=1, column=0, sticky="ew")
        ys.grid(row=0, column=1, sticky="ns")

        mode_box = ttk.LabelFrame(body, text="Hvordan skal kundene importeres?", padding=8)
        mode_box.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.mode = tk.StringVar(value=MERGE)
        ttk.Radiobutton(mode_box, text="Slå sammen med eksisterende kunder (anbefalt)", variable=self.mode,
                        value=MERGE).pack(anchor="w")
        ttk.Label(mode_box, foreground=GREY, wraplength=800, justify="left", text=(
            "Kunder med samme Org.nr – eller, uten Org.nr, samme Firma og Fullt navn – oppdateres med verdiene fra "
            "filen. Tomme celler endrer ingenting. Andre rader legges til. Notater og koordinater beholdes.")
        ).pack(anchor="w", padx=(22, 0))
        ttk.Radiobutton(mode_box, text="Erstatt alle kunder", variable=self.mode, value=REPLACE).pack(
            anchor="w", pady=(6, 0))
        ttk.Label(mode_box, foreground=RED, wraplength=800, justify="left", text=(
            "Alle kunder i databasen slettes først – også notater og koordinater som ikke står i filen. "
            "Det tas en sikkerhetskopi før import.")).pack(anchor="w", padx=(22, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Avbryt", command=self.destroy).pack(side="right")
        self.import_button = ttk.Button(buttons, text="Importer", command=self.run_import, state="disabled")
        self.import_button.pack(side="right", padx=6)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.geometry(f"900x620+{app.winfo_rootx() + 60}+{app.winfo_rooty() + 30}")
        self.minsize(700, 520)
        self.grab_set()
        if path:
            self.after(10, lambda: self.open_file(Path(path)))
        else:
            self.after(10, self.choose_file)

    def choose_file(self) -> None:
        name = filedialog.askopenfilename(parent=self, title="Velg Excel-fil med kunder", filetypes=FILETYPES,
                                          initialdir=str(self.path.parent if self.path else Path.home()))
        if name:
            self.open_file(Path(name))
        elif self.path is None:
            self.destroy()

    def open_file(self, path: Path) -> None:
        self.path = path
        self.file_label.configure(text=str(path), foreground="")
        self.load(None)

    def load(self, sheet_name: str | None) -> None:
        assert self.path is not None
        try:
            self.sheet = excel_io.read_sheet(self.path, sheet_name)
        except ExcelError as exc:
            self.sheet = None
            self.info.configure(text=str(exc), foreground=RED)
            self.preview.delete(*self.preview.get_children())
            self.import_button.state(["disabled"])
            return
        s = self.sheet
        self.sheet_combo.configure(values=s.sheets, state="readonly" if len(s.sheets) > 1 else "disabled")
        self.sheet_var.set(s.sheet)
        lines = [f"Arket «{s.sheet}»: overskrifter på rad {s.header_row}, {len(s.rows)} rader med data."]
        colour = ""
        if s.missing:
            lines.append("Kolonner som mangler (blir tomme for nye kunder): " + ", ".join(s.missing) + ".")
            colour = AMBER
        if s.unknown_headers:
            lines.append("Kolonner som ikke brukes: " + ", ".join(s.unknown_headers) + ".")
        self.info.configure(text="\n".join(lines), foreground=colour)

        keys = list(s.columns.values())
        labels = {**FIELD_LABELS, **excel_io.EXTRA_LABELS}
        configure_columns(self.preview, [("row", "Rad", 45)] + [(k, labels[k], 110) for k in keys])
        self.preview.column("row", stretch=False)
        self.preview.delete(*self.preview.get_children())
        for row_no, values in s.rows[:PREVIEW_ROWS]:
            self.preview.insert("", "end", values=[row_no] + [validation.cell_text(values.get(k)) or "" for k in keys])
        self.import_button.state(["!disabled"] if s.rows else ["disabled"])

    def run_import(self) -> None:
        if self.sheet is None:
            return
        mode = self.mode.get()
        if mode == REPLACE:
            count = len(self.app.customers)
            if not messagebox.askyesno(
                    "Erstatt alle kunder",
                    f"Alle {count} kunder i databasen slettes og erstattes med {len(self.sheet.rows)} rader fra filen.\n\n"
                    "Notater og koordinater som ikke står i filen går tapt. En sikkerhetskopi tas først.\n\n"
                    "Vil du fortsette?", icon="warning", parent=self):
                return
        paths = self.app.paths
        try:
            db.backup_database(paths.db_file, paths.backups_dir, config.BACKUP_KEEP, label="for_import")
            self.summary = excel_io.import_customers(self.app.conn, self.sheet, mode)
        except Exception as exc:  # noqa: BLE001 - the transaction is rolled back; tell the user
            logging.getLogger(__name__).exception("Import feilet")
            messagebox.showerror("Import feilet", f"Ingenting ble importert.\n\n{exc}", parent=self)
            return
        self.destroy()
        self.app.data_changed()
        assert self.path is not None
        show_report(self.app, "Import ferdig", f"Fil: {self.path.name}\n\n{self.summary.text()}")
