"""Batch lookup of coordinates with a progress bar.

A worker thread does the network calls only (rate-limited in Geocoder) and hands results back through
a queue; the main thread writes them to SQLite, one customer at a time, so stopping keeps what was
found. The window is not modal: the advisor can keep working. A result is not stored when the
customer's address changed meanwhile (repo.save_geocode checks).
"""

from __future__ import annotations

import gc
import logging
import queue
import threading
import tkinter as tk
from collections import Counter
from tkinter import ttk
from typing import TYPE_CHECKING

from .. import repo
from ..geocode import Geocoder, GeocodeResult, GeocodeUnavailable
from ..models import GEOCODE_SOURCES, Customer
from .widgets import GREY, RED

if TYPE_CHECKING:
    from .main_window import MainWindow

POLL_MS = 100


class GeocodeDialog(tk.Toplevel):
    def __init__(self, app: MainWindow, customers: list[Customer], replace_manual: bool = False,
                 geocoder: Geocoder | None = None):
        super().__init__(app)
        self.app = app
        self.customers = customers
        self.replace_manual = replace_manual
        self.geocoder = geocoder or Geocoder()
        self.title("Henter koordinater")
        self.transient(app)
        self.resizable(False, False)
        self.queue: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.done_count = 0
        self.found: Counter[str] = Counter()
        self.not_found = 0
        self.skipped = 0
        self.error: str | None = None
        self.finished = False

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Slår opp {len(customers)} kunde(r) hos Kartverket (gnr/bnr → adresse → postnummer).",
                  wraplength=420, justify="left").pack(anchor="w")
        self.bar = ttk.Progressbar(body, mode="determinate", length=420, maximum=max(len(customers), 1))
        self.bar.pack(fill="x", pady=(10, 4))
        self.current = ttk.Label(body, text="", foreground=GREY, width=60)
        self.current.pack(anchor="w")
        self.counts = ttk.Label(body, text="", wraplength=420, justify="left")
        self.counts.pack(anchor="w", pady=(6, 0))
        self.button = ttk.Button(body, text="Stopp", command=self.on_stop)
        self.button.pack(anchor="e", pady=(10, 0))
        self.protocol("WM_DELETE_WINDOW", self.on_stop)
        self.geometry(f"+{app.winfo_rootx() + 160}+{app.winfo_rooty() + 120}")

        app.geocoding = True
        # Tk objects must only be freed by the main thread; the cyclic garbage collector could otherwise run
        # inside the worker. Reference counting still frees everything else. Re-enabled in _finish.
        self._gc_was_enabled = gc.isenabled()
        gc.disable()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self.after(POLL_MS, self._poll)

    # --- Worker thread (no Tk, no SQLite) -----------------------------------------

    def _work(self) -> None:
        try:
            for c in self.customers:
                if self.stop.is_set():
                    break
                self.queue.put(("start", c, None))
                try:
                    result = self.geocoder.geocode(c)
                except GeocodeUnavailable as exc:
                    self.queue.put(("offline", c, str(exc)))
                    return
                self.queue.put(("result", c, result))
        except Exception as exc:  # noqa: BLE001 - handed to the UI thread
            logging.getLogger(__name__).exception("Geokoding feilet")
            self.queue.put(("offline", None, f"Uventet feil: {exc}"))
        finally:
            self.queue.put(("end", None, None))

    # --- Main thread --------------------------------------------------------------

    def _poll(self) -> None:
        try:
            while True:
                kind, c, payload = self.queue.get_nowait()
                if kind == "start":
                    self.current.configure(text=f"{self.done_count + 1} av {len(self.customers)}: {c.display_name}")
                elif kind == "result":
                    self._store(c, payload)
                elif kind == "offline":
                    self.error = payload
                elif kind == "end":
                    self._finish()
                    return
        except queue.Empty:
            pass
        self._show_counts()
        self.after(POLL_MS, self._poll)

    def _store(self, c: Customer, result: GeocodeResult) -> None:
        stored = repo.save_geocode(self.app.conn, c.id, c.address_key(), result.lat, result.lon,  # type: ignore[arg-type]
                                   result.source, result.note, replace_manual=self.replace_manual)
        self.done_count += 1
        self.bar.configure(value=self.done_count)
        if not result.found:
            self.not_found += 1  # existing coordinates, if any, are kept
        elif stored:
            self.found[result.source or ""] += 1
        else:
            self.skipped += 1

    def _show_counts(self) -> None:
        parts = [f"{GEOCODE_SOURCES[k]} {n}" for k, n in self.found.items() if n]
        text = f"Funnet: {sum(self.found.values())}" + (f" ({', '.join(parts)})" if parts else "")
        text += f" · Ikke funnet: {self.not_found}"
        if self.skipped:
            text += f" · Ikke lagret (endret underveis): {self.skipped}"
        self.counts.configure(text=text)

    def on_stop(self) -> None:
        if self.finished:
            self.destroy()
            return
        self.stop.set()
        self.button.state(["disabled"])
        self.current.configure(text="Stopper etter denne kunden …")

    def _finish(self) -> None:
        self.finished = True
        if self._gc_was_enabled:
            gc.enable()
        self.app.geocoding = False
        self._show_counts()
        remaining = len(self.customers) - self.done_count
        if self.error:
            self.current.configure(text=f"Stoppet: {self.error}", foreground=RED, wraplength=420)
        elif remaining:
            self.current.configure(text=f"Stoppet. {remaining} kunde(r) ble ikke slått opp – kjør igjen senere.")
        else:
            self.current.configure(text="Ferdig.")
        self.button.configure(text="Lukk")
        self.button.state(["!disabled"])
        self.app.data_changed()
        self.app.set_status(f"Koordinater: {sum(self.found.values())} funnet, {self.not_found} ikke funnet"
                            + (f", {remaining} ikke slått opp" if remaining else "") + ".")
