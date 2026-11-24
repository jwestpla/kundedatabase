"""Customer table: ☐/☑ checkbox in the first column, sortable columns, coordinates column."""

from __future__ import annotations

import re
from tkinter import ttk
from typing import Callable

from ..models import GEOCODE_SOURCES, Customer
from .widgets import MISSING_BG, scrolled_tree, stripe

UNCHECKED, CHECKED = "☐", "☑"
MISSING_TEXT = "⚠ Mangler"
NOT_FOUND_TEXT = "⚠ Ikke funnet"

COLUMNS = [
    ("checked", CHECKED, 34),
    ("company", "Firma", 180),
    ("full_name", "Fullt navn", 150),
    ("category", "Kategori", 100),
    ("place", "Sted", 110),
    ("postcode", "Postnr", 60),
    ("address", "Adresse 1", 150),
    ("phone", "Telefon", 100),
    ("email", "E-post", 170),
    ("org_nr", "Org.nr", 85),
    ("kommunenr", "Kommunenr", 75),
    ("gnr_bnr", "Gnr og bnr", 80),
    ("coords", "Koordinater", 110),
]
_NUMBER = re.compile(r"(\d+)")


def coords_text(c: Customer) -> str:
    if c.has_coordinates:
        return GEOCODE_SOURCES.get(c.geocode_source or "", "Ja")
    return NOT_FOUND_TEXT if c.geocode_failed else MISSING_TEXT


def _sort_key(text: str) -> tuple:
    """Natural, case-insensitive order (2 before 10); empty values last."""
    text = (text or "").strip().casefold()
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in _NUMBER.split(text) if p)
    return (not text, parts)


class CustomerList(ttk.Frame):
    """Shows the given customers. The checked ids live in the caller's set and survive filtering."""

    def __init__(self, master, checked: set[int], on_select: Callable[[int | None], None],
                 on_toggle: Callable[[], None], on_open: Callable[[int], None]):
        super().__init__(master)
        self.checked = checked
        self.on_select, self.on_toggle, self.on_open = on_select, on_toggle, on_open
        self.customers: list[Customer] = []
        self.sort_key, self.sort_reverse = "company", False
        frame, self.tree = scrolled_tree(self, COLUMNS, height=15, xscroll=True)
        frame.pack(fill="both", expand=True)
        self.tree.column("checked", anchor="center", stretch=False, width=34, minwidth=34)
        self.tree.heading("checked", anchor="center")
        for key, heading, _w in COLUMNS:
            self.tree.heading(key, command=lambda k=key: self.sort_by(k))
        self.tree.tag_configure("missing", background=MISSING_BG)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", lambda _e: self._open_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select(self.selected_id()))
        self._update_headings()

    # --- Content ----------------------------------------------------------------

    def show(self, customers: list[Customer], keep: int | None = None) -> None:
        """Replace the rows. Keeps the highlighted row (or `keep`) and the scroll position when possible."""
        keep = keep if keep is not None else self.selected_id()
        top = self.tree.yview()[0]
        self.customers = list(customers)
        self.tree.delete(*self.tree.get_children())
        for c in self._sorted(self.customers):
            self.tree.insert("", "end", iid=str(c.id), values=self._values(c),
                             tags=() if c.has_coordinates else ("missing",))
        stripe(self.tree, skip=("missing",))
        self.tree.yview_moveto(top)
        if keep is not None and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
            self.tree.focus(str(keep))
        else:
            self.on_select(None)

    def _values(self, c: Customer) -> tuple:
        return (CHECKED if c.id in self.checked else UNCHECKED, c.company or "", c.full_name or "",
                c.category or "", c.place or "", c.postcode or "", c.address or "", c.phone or "", c.email or "",
                c.org_nr or "", c.kommunenr or "", c.gnr_bnr or "", coords_text(c))

    def visible_ids(self) -> list[int]:
        return [int(i) for i in self.tree.get_children()]

    def refresh_checks(self) -> None:
        """Redraw only the checkbox column (after Velg alle / Fjern alle / Inverter)."""
        for iid in self.tree.get_children():
            self.tree.set(iid, "checked", CHECKED if int(iid) in self.checked else UNCHECKED)

    def selected_id(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def select(self, customer_id: int) -> None:
        if self.tree.exists(str(customer_id)):
            self.tree.selection_set(str(customer_id))
            self.tree.focus(str(customer_id))
            self.tree.see(str(customer_id))

    # --- Sorting ----------------------------------------------------------------

    def sort_by(self, key: str) -> None:
        if key == self.sort_key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key, self.sort_reverse = key, False
        self._update_headings()
        self.show(self.customers)

    def _sorted(self, customers: list[Customer]) -> list[Customer]:
        if self.sort_key == "checked":
            key = lambda c: (c.id not in self.checked, _sort_key(c.company or c.full_name or ""))  # noqa: E731
        elif self.sort_key == "coords":
            key = lambda c: _sort_key(coords_text(c))  # noqa: E731
        else:
            key = lambda c: (_sort_key(getattr(c, self.sort_key) or ""),  # noqa: E731
                             _sort_key(c.company or c.full_name or ""))
        return sorted(customers, key=key, reverse=self.sort_reverse)

    def _update_headings(self) -> None:
        for key, heading, _w in COLUMNS:
            arrow = (" ▼" if self.sort_reverse else " ▲") if key == self.sort_key else ""
            self.tree.heading(key, text=heading + arrow)

    # --- Events -----------------------------------------------------------------

    def _toggle(self, iid: str) -> None:
        customer_id = int(iid)
        if customer_id in self.checked:
            self.checked.discard(customer_id)
        else:
            self.checked.add(customer_id)
        self.tree.set(iid, "checked", CHECKED if customer_id in self.checked else UNCHECKED)
        self.on_toggle()

    def _on_click(self, event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return None
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)
            self.tree.focus(iid)
        return "break"  # a checkbox click doesn't change the highlighted customer

    def _on_space(self, _event=None) -> str:
        iid = self.tree.focus() or (self.tree.selection() or [None])[0]
        if iid:
            self._toggle(iid)
        return "break"

    def _on_double(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) == "cell" and self.tree.identify_column(event.x) != "#1":
            self._open_selected()

    def _open_selected(self) -> None:
        customer_id = self.selected_id()
        if customer_id is not None:
            self.on_open(customer_id)
