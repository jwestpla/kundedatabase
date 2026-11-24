"""Main window: toolbar with quick search, selection criteria, customer list + details, selection bar,
status bar.

All customers are held in memory (a register of a few thousand is small); search and criteria are
applied in Python. After any write, call data_changed(). The ☑ selection is a set of ids that survives
searching and filtering.
"""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__, map_export, repo
from ..config import Paths
from ..filters import search_matches
from ..geocode import google_maps_url
from ..models import Customer
from ..validation import warnings
from .customer_dialog import CustomerDialog
from .customer_list import CustomerList
from .detail_panel import DetailPanel
from .export_dialog import ExportDialog
from .filter_panel import FilterPanel
from .geocode_dialog import GeocodeDialog
from .import_dialog import ImportDialog
from .settings_dialog import SettingsDialog
from .widgets import AMBER, GREY, open_path, show_errors

SEARCH_DEBOUNCE_MS = 200


class MainWindow(tk.Tk):
    def __init__(self, conn: sqlite3.Connection, paths: Paths):
        super().__init__()
        self.conn = conn
        self.paths = paths
        self.customers: list[Customer] = []
        self.by_id: dict[int, Customer] = {}
        self.checked: set[int] = set()
        self.geocoding = False
        self._search_job: str | None = None

        self.title(f"Kundedatabase – versjon {__version__}")
        width = min(1280, self.winfo_screenwidth() - 40)
        height = min(780, self.winfo_screenheight() - 90)  # leave room for the Windows taskbar
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(min(820, width), min(520, height))
        # Rows tall enough for the font, so text isn't clipped on scaled (125 %+) Windows screens.
        linespace = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self).configure("Treeview", rowheight=linespace + 6)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.search_var = tk.StringVar()
        self.only_checked = tk.BooleanVar(value=False)

        self._build_menu()
        self._build_toolbar()
        self.filter_panel = FilterPanel(self, paths.filters_file, on_change=self.apply_view,
                                        on_select_hits=self.select_hits)
        self.filter_panel.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
        self.filter_panel.grid_remove()
        self._build_body()
        self._build_selection_bar()
        self._build_statusbar()

        self.search_var.trace_add("write", lambda *_: self._search_soon())
        for seq in ("<Control-f>", "<Command-f>"):
            self.bind(seq, lambda _e: self._focus_search())
        for seq in ("<Control-n>", "<Command-n>"):
            self.bind(seq, lambda _e: self.new_customer())
        self.data_changed()
        if not self.customers:
            self.set_status("Databasen er tom. Bruk «Importer fra Excel…» eller «Ny kunde».")

    # --- Layout -------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Importer fra Excel…", command=self.import_excel)
        file_menu.add_command(label="Eksporter til Excel…", command=self.export)
        file_menu.add_separator()
        file_menu.add_command(label="Innstillinger…", command=self.open_settings)
        file_menu.add_command(label="Åpne datamappen", command=lambda: open_path(self.paths.data_dir))
        file_menu.add_separator()
        file_menu.add_command(label="Avslutt", command=self.destroy)
        menubar.add_cascade(label="Fil", menu=file_menu)

        customer_menu = tk.Menu(menubar, tearoff=False)
        customer_menu.add_command(label="Ny kunde…", command=self.new_customer)
        customer_menu.add_command(label="Rediger…", command=self.edit_selected)
        customer_menu.add_command(label="Vis i Google Maps", command=self.open_maps)
        customer_menu.add_separator()
        customer_menu.add_command(label="Slett…", command=self.delete_selected)
        customer_menu.add_command(label="Slett valgte (☑)…", command=self.delete_checked)
        menubar.add_cascade(label="Kunde", menu=customer_menu)

        geo_menu = tk.Menu(menubar, tearoff=False)
        geo_menu.add_command(label="Hent manglende koordinater…", command=self.geocode_missing)
        geo_menu.add_command(label="Prøv igjen for «ikke funnet»…", command=self.geocode_failed)
        geo_menu.add_command(label="Hent på nytt for valgte (☑)…", command=self.geocode_checked)
        menubar.add_cascade(label="Koordinater", menu=geo_menu)

        map_menu = tk.Menu(menubar, tearoff=False)
        map_menu.add_command(label="Vis utvalget på kart", command=self.show_map)
        map_menu.add_command(label="Eksporter KML (Google My Maps)…", command=self.export_kml)
        menubar.add_cascade(label="Kart", menu=map_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Om Kundedatabase", command=self._show_about)
        menubar.add_cascade(label="Hjelp", menu=help_menu)
        self.configure(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 8, 8, 6))
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text="Søk").pack(side="left")
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=32)
        self.search_entry.pack(side="left", padx=(6, 2))
        self.search_entry.bind("<Escape>", lambda _e: self.search_var.set(""))
        ttk.Button(bar, text="✕", width=3, command=lambda: self.search_var.set("")).pack(side="left")
        self.filter_button = ttk.Button(bar, text="Utvalgskriterier ▸", command=self.toggle_filters)
        self.filter_button.pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Ny kunde", command=self.new_customer).pack(side="right")
        ttk.Button(bar, text="Eksporter…", command=self.export).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Importer…", command=self.import_excel).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Vis på kart", command=self.show_map).pack(side="right", padx=(0, 12))
        ttk.Button(bar, text="Hent manglende koordinater", command=self.geocode_missing).pack(side="right", padx=(0, 6))

    def _build_body(self) -> None:
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.grid(row=2, column=0, sticky="nsew", padx=8)
        self.list = CustomerList(pane, self.checked, on_select=self._on_select, on_toggle=self._update_status,
                                 on_open=self.edit_customer)
        self.detail = DetailPanel(pane, {"edit": self.edit_selected, "maps": self.open_maps,
                                         "geocode": self.geocode_selected, "delete": self.delete_selected})
        pane.add(self.list, weight=4)
        pane.add(self.detail, weight=1)

    def _build_selection_bar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6, 8, 0))
        bar.grid(row=3, column=0, sticky="ew")
        ttk.Label(bar, text="Utvalg (☑):").pack(side="left")
        for text, command in (("Velg alle synlige", self.check_visible), ("Fjern alle", self.uncheck_all),
                              ("Inverter", self.invert_visible)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(bar, text="Vis bare valgte", variable=self.only_checked,
                        command=self.apply_view).pack(side="left", padx=(12, 0))
        ttk.Label(bar, text="Klikk i ☐-kolonnen eller trykk mellomrom for å velge. Dobbeltklikk for å redigere.",
                  foreground=GREY).pack(side="right")

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 4))
        bar.grid(row=4, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.status_label = ttk.Label(bar, text="", font=("TkDefaultFont", 0, "bold"))
        self.status_label.grid(row=0, column=0, sticky="w")
        self.counts_label = ttk.Label(bar, text="")
        self.counts_label.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.message_label = ttk.Label(bar, text="", foreground="#555555")
        self.message_label.grid(row=0, column=2, sticky="e")

    # --- State --------------------------------------------------------------------

    def data_changed(self, select: int | None = None) -> None:
        """Reload all customers from the database and redraw."""
        self.customers = repo.list_customers(self.conn)
        self.by_id = {c.id: c for c in self.customers}  # type: ignore[misc]
        self.checked.intersection_update(self.by_id)
        self.apply_view(select)

    def visible_customers(self) -> list[Customer]:
        query = self.search_var.get()
        spec = self.filter_panel.spec()
        only_hits = self.filter_panel.only_hits.get() and not spec.is_empty()
        only_checked = self.only_checked.get()
        return [c for c in self.customers
                if search_matches(c, query)
                and (not only_hits or spec.matches(c))
                and (not only_checked or c.id in self.checked)]

    def apply_view(self, select: int | None = None) -> None:
        spec = self.filter_panel.spec()
        self.filter_panel.show_hits(None if spec.is_empty() else sum(spec.matches(c) for c in self.customers))
        self.list.show(self.visible_customers(), keep=select)
        if select is not None:
            self.list.select(select)
        self._update_status()

    def _search_soon(self) -> None:
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(SEARCH_DEBOUNCE_MS, self._run_search)

    def _run_search(self) -> None:
        self._search_job = None
        self.apply_view()

    def _focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def toggle_filters(self) -> None:
        if self.filter_panel.winfo_ismapped():
            self.filter_panel.grid_remove()
            self.filter_button.configure(text="Utvalgskriterier ▸")
        else:
            self.filter_panel.grid()
            self.filter_button.configure(text="Utvalgskriterier ▾")

    def _on_select(self, customer_id: int | None) -> None:
        self.detail.show(self.by_id.get(customer_id) if customer_id is not None else None)

    def selected(self) -> Customer | None:
        customer_id = self.list.selected_id()
        return self.by_id.get(customer_id) if customer_id is not None else None

    def set_status(self, message: str) -> None:
        self.message_label.configure(text=message)

    def _update_status(self) -> None:
        total = len(self.customers)
        self.status_label.configure(text=f"{len(self.checked)} valgt av {total}")
        missing = sum(1 for c in self.customers if not c.has_coordinates)
        text = f"· {len(self.list.customers)} vises"
        if missing:
            text += f" · {missing} uten koordinater"
        self.counts_label.configure(text=text, foreground=AMBER if missing else "")

    # --- Selection (☑) ------------------------------------------------------------

    def check_visible(self) -> None:
        self.checked.update(self.list.visible_ids())
        self._after_check_change()

    def uncheck_all(self) -> None:
        self.checked.clear()
        self._after_check_change()

    def invert_visible(self) -> None:
        for customer_id in self.list.visible_ids():
            self.checked.symmetric_difference_update({customer_id})
        self._after_check_change()

    def select_hits(self, add: bool) -> None:
        spec = self.filter_panel.spec()
        if spec.is_empty():
            messagebox.showinfo("Utvalgskriterier", "Fyll ut minst ett kriterium først.", parent=self)
            return
        hits = {c.id for c in self.customers if spec.matches(c)}
        before = len(self.checked)
        if not add:
            self.checked.clear()
        self.checked.update(hits)  # type: ignore[arg-type]
        self._after_check_change()
        if add:
            self.set_status(f"{len(hits)} treff, {len(self.checked) - before} lagt til utvalget.")
        else:
            self.set_status(f"Utvalget er nå de {len(hits)} treffene.")

    def _after_check_change(self) -> None:
        if self.only_checked.get():
            self.apply_view()
        else:
            self.list.refresh_checks()
            self._update_status()

    def checked_customers(self) -> list[Customer]:
        return [c for c in self.customers if c.id in self.checked]

    # --- Customers ----------------------------------------------------------------

    def new_customer(self) -> None:
        dialog = CustomerDialog(self, self.conn)
        if dialog.show() and dialog.result:
            self._saved(dialog.result, "Lagt til")

    def edit_selected(self) -> None:
        c = self.selected()
        if c is not None:
            self.edit_customer(c.id)  # type: ignore[arg-type]

    def edit_customer(self, customer_id: int) -> None:
        c = repo.get_customer(self.conn, customer_id)
        if c is None:
            self.data_changed()
            return
        dialog = CustomerDialog(self, self.conn, c)
        if dialog.show() and dialog.result:
            self._saved(dialog.result, "Lagret")

    def _saved(self, c: Customer, verb: str) -> None:
        if self.search_var.get() and not search_matches(c, self.search_var.get()):
            self.search_var.set("")  # make sure the customer is visible
        self.data_changed(select=c.id)
        n = len(warnings(c))
        self.set_status(f"{verb} {c.display_name}." + (f" {n} advarsel(er) – se detaljene." if n else ""))

    def delete_selected(self) -> None:
        c = self.selected()
        if c is None:
            return
        if not messagebox.askyesno("Slett kunde", f"Slette «{c.display_name}»?\n\nDette kan ikke angres.",
                                   icon="warning", parent=self):
            return
        repo.delete_customers(self.conn, [c.id])  # type: ignore[list-item]
        self.data_changed()
        self.set_status(f"Slettet {c.display_name}.")

    def delete_checked(self) -> None:
        customers = self.checked_customers()
        if not customers:
            messagebox.showinfo("Slett valgte", "Ingen kunder er valgt (☑).", parent=self)
            return
        names = "\n".join(f"• {c.display_name}" for c in customers[:10])
        more = f"\n… og {len(customers) - 10} til" if len(customers) > 10 else ""
        if not messagebox.askyesno("Slett valgte kunder",
                                   f"Slette {len(customers)} kunde(r)?\n\n{names}{more}\n\nDette kan ikke angres.",
                                   icon="warning", parent=self):
            return
        repo.delete_customers(self.conn, [c.id for c in customers])  # type: ignore[misc]
        self.data_changed()
        self.set_status(f"Slettet {len(customers)} kunde(r).")

    def open_maps(self) -> None:
        c = self.selected()
        if c is None:
            return
        url = google_maps_url(c)
        if url is None:
            messagebox.showinfo("Vis i Google Maps", "Kunden har verken koordinater eller adresse.", parent=self)
            return
        webbrowser.open(url)
        if not c.has_coordinates:
            self.set_status("Kunden mangler koordinater – Google Maps søker på adressen.")

    # --- Coordinates --------------------------------------------------------------

    def _start_geocoding(self, customers: list[Customer], what: str, replace_manual: bool = False) -> None:
        if self.geocoding:
            messagebox.showinfo("Koordinater", "Et oppslag pågår allerede.", parent=self)
            return
        if not customers:
            messagebox.showinfo("Koordinater", f"Ingen kunder å slå opp ({what}).", parent=self)
            return
        GeocodeDialog(self, customers, replace_manual=replace_manual)

    def geocode_missing(self) -> None:
        todo = [c for c in self.customers if not c.has_coordinates and not c.geocode_failed]
        if todo and len(todo) > 1 and not messagebox.askyesno(
                "Hent manglende koordinater",
                f"Slå opp koordinater for {len(todo)} kunder hos Kartverket?\n\nDet tar omtrent "
                f"{max(1, round(len(todo) * 0.6 / 60))} minutt(er). Du kan stoppe underveis og fortsette senere.",
                parent=self):
            return
        self._start_geocoding(todo, "alle har koordinater eller er forsøkt slått opp")

    def geocode_failed(self) -> None:
        self._start_geocoding([c for c in self.customers if c.geocode_failed], "ingen med «ikke funnet»")

    def geocode_checked(self) -> None:
        customers = self.checked_customers()
        replace_manual = False
        manual = sum(1 for c in customers if c.geocode_source == "manuell")
        if manual:
            answer = messagebox.askyesnocancel(
                "Manuelle koordinater",
                f"{manual} av de valgte kundene har koordinater satt manuelt.\n\n"
                "Ja: erstatt dem med oppslag hos Kartverket.\nNei: behold dem (de hoppes over).", parent=self)
            if answer is None:
                return
            replace_manual = answer
            if not answer:
                customers = [c for c in customers if c.geocode_source != "manuell"]
        self._start_geocoding(customers, "ingen kunder er valgt (☑)", replace_manual)

    def geocode_selected(self) -> None:
        c = self.selected()
        if c is None:
            return
        replace_manual = False
        if c.geocode_source == "manuell":
            if not messagebox.askyesno("Manuelle koordinater",
                                       "Kunden har koordinater satt manuelt. Erstatte dem med oppslag hos Kartverket?\n"
                                       "(Finnes ingenting, beholdes de.)", parent=self):
                return
            replace_manual = True
        self._start_geocoding([c], "", replace_manual)

    # --- Excel --------------------------------------------------------------------

    def import_excel(self) -> None:
        dialog = ImportDialog(self)
        self.wait_window(dialog)
        summary = dialog.summary
        if summary is None:
            return
        self.set_status(f"Importert: {summary.new} nye, {summary.updated} oppdatert.")
        todo = [self.by_id[i] for i in summary.touched_ids
                if i in self.by_id and not self.by_id[i].has_coordinates and not self.by_id[i].geocode_failed]
        if todo and not self.geocoding and messagebox.askyesno(
                "Koordinater", f"{len(todo)} av de importerte kundene mangler koordinater. Slå dem opp nå?\n\n"
                               "(Kan også gjøres senere fra menyen Koordinater.)", parent=self):
            self._start_geocoding(todo, "")

    def export(self) -> None:
        if not self.customers:
            messagebox.showinfo("Eksporter", "Ingen kunder å eksportere.", parent=self)
            return
        ExportDialog(self)

    # --- Maps ---------------------------------------------------------------------

    def _map_customers(self, what: str) -> list[Customer] | None:
        """The ☑ customers; if none, offer the customers in the list. Warns about missing coordinates."""
        customers = self.checked_customers()
        if not customers:
            visible = list(self.list.customers)
            if not visible or not messagebox.askyesno(
                    what, f"Ingen kunder er valgt (☑). Bruke de {len(visible)} kundene som vises i listen?",
                    parent=self):
                return None
            customers = visible
        missing = [c for c in customers if not c.has_coordinates]
        if len(missing) == len(customers):
            messagebox.showwarning(what, "Ingen av kundene har koordinater. Bruk menyen Koordinater først.",
                                   parent=self)
            return None
        if missing:
            names = "\n".join(f"• {c.display_name}" for c in missing[:15])
            more = f"\n… og {len(missing) - 15} til" if len(missing) > 15 else ""
            if not messagebox.askokcancel(
                    what, f"{len(missing)} av {len(customers)} kunde(r) mangler koordinater og blir ikke med:\n\n"
                          f"{names}{more}\n\nFortsette med de {len(customers) - len(missing)} andre?",
                    icon="warning", parent=self):
                return None
        return customers

    def show_map(self) -> None:
        customers = self._map_customers("Vis på kart")
        if customers is None:
            return
        pins, missing, legend = map_export.build_pins(customers)
        settings = repo.get_settings(self.conn)
        title = map_export.map_title(len(pins))
        key = settings.get("google_maps_api_key", "").strip()
        if key:
            html = map_export.google_html(pins, missing, legend, key, title)
        else:
            html = map_export.leaflet_html(pins, missing, legend, settings.get("map_background", "kartverket"), title)
        try:
            path = map_export.write_map_file(self.paths.export_dir, html)
        except OSError as exc:
            show_errors(self, [f"Kunne ikke skrive kartfilen:\n{exc}"], "Kart")
            return
        webbrowser.open(path.as_uri())
        self.set_status(f"Kart med {len(pins)} kunde(r) åpnet i nettleseren ({path.name}).")

    def export_kml(self) -> None:
        customers = self._map_customers("Eksporter KML")
        if customers is None:
            return
        pins, _missing, legend = map_export.build_pins(customers)
        self.paths.export_dir.mkdir(parents=True, exist_ok=True)
        name = filedialog.asksaveasfilename(
            parent=self, title="Eksporter KML", defaultextension=".kml", filetypes=[("KML", "*.kml")],
            initialdir=str(self.paths.export_dir), initialfile=f"Kunder_{date.today().isoformat()}.kml")
        if not name:
            return
        try:
            Path(name).write_text(map_export.kml(pins, legend, f"Kunder {date.today():%d.%m.%Y}"), encoding="utf-8")
        except OSError as exc:
            show_errors(self, [f"Kunne ikke skrive filen:\n{exc}"], "Eksporter KML")
            return
        self.set_status(f"KML med {len(pins)} kunde(r) lagret: {Path(name).name}.")
        messagebox.showinfo(
            "KML lagret", f"{len(pins)} kunde(r) lagret i\n{name}\n\nI Google My Maps (mymaps.google.com): lag et nytt "
                          "kart, trykk «Importer» i et lag og velg filen.", parent=self)

    def open_settings(self) -> None:
        if SettingsDialog(self, self.conn).show():
            self.set_status("Innstillinger lagret.")

    # --- Misc ---------------------------------------------------------------------

    def report_callback_exception(self, exc, val, tb) -> None:
        """Unexpected errors: log them and tell the user, instead of failing silently (no console on Windows)."""
        logging.getLogger(__name__).error("Uventet feil", exc_info=(exc, val, tb))
        messagebox.showerror(
            "Uventet feil",
            f"Det oppstod en uventet feil:\n{val}\n\nDetaljene er lagret i {self.paths.log_file}.", parent=self)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "Om Kundedatabase",
            f"Kundedatabase\nVersjon {__version__}\n\nDatamappe: {self.paths.data_dir}\nLogg: {self.paths.log_file}\n\n"
            "Koordinater: Kartverket (Eiendom, Adresse og Stedsnavn API), CC BY 4.0.", parent=self)
