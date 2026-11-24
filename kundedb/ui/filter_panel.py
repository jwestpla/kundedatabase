"""Selection criteria: rows of [felt] [operator] [verdi], combined with OG/ELLER, saved by name."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from ..filters import (
    AND, CONTAINS, FIELD_BY_LABEL, FILTER_FIELDS, LABEL_BY_FIELD, NO_VALUE, OPERATORS, OR, Criterion, FilterSpec,
    load_filters, save_filters,
)
from ..models import FRUITS, LIST_FIELDS
from .widgets import GREY

DEBOUNCE_MS = 250


class _Row:
    def __init__(self, panel: FilterPanel, criterion: Criterion):
        self.panel = panel
        self.frame = ttk.Frame(panel.rows_frame)
        self.field = tk.StringVar(value=LABEL_BY_FIELD.get(criterion.field, FILTER_FIELDS[0][1]))
        self.operator = tk.StringVar(value=criterion.operator if criterion.operator in OPERATORS else CONTAINS)
        self.value = tk.StringVar(value=criterion.value)
        ttk.Combobox(self.frame, textvariable=self.field, values=[label for _, label in FILTER_FIELDS],
                     state="readonly", width=18).pack(side="left")
        ttk.Combobox(self.frame, textvariable=self.operator, values=list(OPERATORS), state="readonly",
                     width=12).pack(side="left", padx=4)
        self.entry = ttk.Entry(self.frame, textvariable=self.value, width=28)
        self.entry.pack(side="left")
        ttk.Button(self.frame, text="✕", width=3, command=lambda: panel.remove_row(self)).pack(side="left", padx=(4, 0))
        self.hint = ttk.Label(self.frame, text="", foreground=GREY)
        self.hint.pack(side="left", padx=(6, 0))
        for var in (self.field, self.operator):
            var.trace_add("write", lambda *_: self._changed(now=True))
        self.value.trace_add("write", lambda *_: self._changed(now=False))
        self._update_entry()

    def _update_entry(self) -> None:
        op = self.operator.get()
        self.entry.state(["disabled"] if op in NO_VALUE else ["!disabled"])
        if FIELD_BY_LABEL.get(self.field.get()) in LIST_FIELDS and op not in NO_VALUE:
            hint = {"en av": "har minst én av", "er lik": "har akkurat disse", "er ikke": "har ingen av",
                    "inneholder": "har"}.get(op, "")
            self.hint.configure(text=f"{hint}: {', '.join(FRUITS)}".lstrip(": "))
        else:
            self.hint.configure(text="skill verdiene med komma" if op == "en av" else "")

    def _changed(self, now: bool) -> None:
        self._update_entry()
        self.panel.changed(now)

    def criterion(self) -> Criterion:
        return Criterion(FIELD_BY_LABEL.get(self.field.get(), ""), self.operator.get(), self.value.get())


class FilterPanel(ttk.LabelFrame):
    def __init__(self, master, filters_file: Path, on_change: Callable[[], None],
                 on_select_hits: Callable[[bool], None]):
        super().__init__(master, text="Utvalgskriterier", padding=8)
        self.filters_file = filters_file
        self.on_change = on_change
        self._pending: str | None = None
        self.rows: list[_Row] = []

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.grid(row=0, column=0, columnspan=2, sticky="w")

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(controls, text="+ Legg til kriterium", command=lambda: self.add_row()).pack(side="left")
        ttk.Label(controls, text="Kombiner med").pack(side="left", padx=(14, 4))
        self.combine = tk.StringVar(value=AND)
        ttk.Radiobutton(controls, text="OG (alle må stemme)", variable=self.combine, value=AND,
                        command=lambda: self.changed(True)).pack(side="left")
        ttk.Radiobutton(controls, text="ELLER (minst ett)", variable=self.combine, value=OR,
                        command=lambda: self.changed(True)).pack(side="left", padx=(6, 0))
        self.only_hits = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Vis bare treff i listen", variable=self.only_hits,
                        command=lambda: self.changed(True)).pack(side="left", padx=(14, 0))

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.hits_label = ttk.Label(actions, text="", width=14)
        self.hits_label.pack(side="left")
        ttk.Button(actions, text="Velg alle treff", command=lambda: on_select_hits(False)).pack(side="left")
        ttk.Button(actions, text="Legg treff til utvalg", command=lambda: on_select_hits(True)).pack(
            side="left", padx=(6, 0))
        ttk.Button(actions, text="Nullstill", command=self.clear).pack(side="left", padx=(6, 0))

        saved = ttk.Frame(self)
        saved.grid(row=1, column=1, rowspan=2, sticky="se", padx=(20, 0))
        ttk.Label(saved, text="Lagrede utvalg").grid(row=0, column=0, columnspan=3, sticky="w")
        self.saved_var = tk.StringVar()
        self.saved_combo = ttk.Combobox(saved, textvariable=self.saved_var, state="readonly", width=22)
        self.saved_combo.grid(row=1, column=0, sticky="w")
        self.saved_combo.bind("<<ComboboxSelected>>", lambda _e: self.load_saved(self.saved_var.get()))
        ttk.Button(saved, text="Lagre som…", command=self.save_as).grid(row=1, column=1, padx=(6, 0))
        ttk.Button(saved, text="Slett", command=self.delete_saved).grid(row=1, column=2, padx=(6, 0))
        self.columnconfigure(1, weight=1)

        self.add_row(notify=False)
        self._reload_saved()

    # --- Rows -------------------------------------------------------------------

    def add_row(self, criterion: Criterion | None = None, notify: bool = True) -> None:
        row = _Row(self, criterion or Criterion(FILTER_FIELDS[0][0]))
        row.frame.pack(anchor="w", pady=1)
        self.rows.append(row)
        if notify:
            self.changed(True)
            row.entry.focus_set()

    def remove_row(self, row: _Row) -> None:
        row.frame.destroy()
        self.rows.remove(row)
        if not self.rows:
            self.add_row(notify=False)
        self.changed(True)

    def clear(self) -> None:
        for row in list(self.rows):
            row.frame.destroy()
        self.rows.clear()
        self.combine.set(AND)
        self.saved_var.set("")
        self.add_row(notify=False)
        self.changed(True)

    def spec(self) -> FilterSpec:
        return FilterSpec([r.criterion() for r in self.rows], self.combine.get())

    def set_spec(self, spec: FilterSpec) -> None:
        for row in list(self.rows):
            row.frame.destroy()
        self.rows.clear()
        for c in spec.criteria or [Criterion(FILTER_FIELDS[0][0])]:
            self.add_row(c, notify=False)
        self.combine.set(spec.combine)
        self.changed(True)

    def changed(self, now: bool) -> None:
        if self._pending:
            self.after_cancel(self._pending)
            self._pending = None
        if now:
            self.on_change()
        else:
            self._pending = self.after(DEBOUNCE_MS, self._fire)

    def _fire(self) -> None:
        self._pending = None
        self.on_change()

    def show_hits(self, count: int | None) -> None:
        self.hits_label.configure(text="Ingen kriterier" if count is None else f"{count} treff")

    # --- Saved filters ----------------------------------------------------------

    def _reload_saved(self) -> None:
        self.saved = load_filters(self.filters_file)
        self.saved_combo.configure(values=sorted(self.saved, key=str.casefold))

    def load_saved(self, name: str) -> None:
        spec = self.saved.get(name)
        if spec is not None:
            self.set_spec(spec)
            self.saved_var.set(name)

    def save_as(self) -> None:
        spec = self.spec()
        if spec.is_empty():
            messagebox.showinfo("Lagre utvalg", "Fyll ut minst ett kriterium først.", parent=self)
            return
        name = simpledialog.askstring("Lagre utvalg", "Navn på utvalget:", initialvalue=self.saved_var.get(),
                                      parent=self)
        name = (name or "").strip()
        if not name:
            return
        self._reload_saved()
        if name in self.saved and not messagebox.askyesno(
                "Lagre utvalg", f"Det finnes allerede et utvalg som heter «{name}». Erstatte det?", parent=self):
            return
        self.saved[name] = FilterSpec([c for c in spec.criteria if c.complete], spec.combine)
        try:
            save_filters(self.filters_file, self.saved)
        except OSError as exc:
            messagebox.showerror("Lagre utvalg", f"Kunne ikke lagre {self.filters_file}:\n{exc}", parent=self)
            return
        self._reload_saved()
        self.saved_var.set(name)

    def delete_saved(self) -> None:
        name = self.saved_var.get()
        if not name or name not in self.saved:
            return
        if not messagebox.askyesno("Slett utvalg", f"Slette det lagrede utvalget «{name}»?", parent=self):
            return
        del self.saved[name]
        try:
            save_filters(self.filters_file, self.saved)
        except OSError as exc:
            messagebox.showerror("Slett utvalg", f"Kunne ikke lagre {self.filters_file}:\n{exc}", parent=self)
        self._reload_saved()
        self.saved_var.set("")
