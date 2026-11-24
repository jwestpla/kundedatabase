"""Reusable form, table and dialog helpers (same look and behaviour as Gjødselplan)."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Iterable, Sequence

RED = "#b00020"
AMBER = "#a15c00"
GREEN = "#1b7a2f"
GREY = "#666666"
BLUE = "#1f5fbf"
STRIPE = "#f2f4f1"
MISSING_BG = "#fff1dc"  # rows of customers without coordinates

Choices = Sequence[tuple[str, str]]  # (stored code, displayed label)


def show_errors(parent: tk.Misc, errors: list[str], title: str = "Kan ikke lagre") -> None:
    text = errors[0] if len(errors) == 1 else "\n".join(f"• {e}" for e in errors)
    messagebox.showerror(title, text, parent=parent)


def show_report(parent: tk.Misc, title: str, text: str, width: int = 90, height: int = 20) -> None:
    """A modal window with a read-only, scrollable text (import summaries and other long messages)."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    frame = ttk.Frame(win, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    lines = text.count("\n") + 1
    box = tk.Text(frame, width=width, height=min(max(lines, 6), height), wrap="word", font="TkDefaultFont")
    box.insert("1.0", text)
    box.configure(state="disabled")
    box.grid(row=0, column=0, sticky="nsew")
    if lines > height:
        ys = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky="ns")
    ttk.Button(frame, text="OK", command=win.destroy).grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
    win.bind("<Escape>", lambda _e: win.destroy())
    win.bind("<Return>", lambda _e: win.destroy())
    top = parent.winfo_toplevel()
    win.geometry(f"+{top.winfo_rootx() + 120}+{top.winfo_rooty() + 80}")
    win.grab_set()
    win.focus_set()
    win.wait_window()


def scrolled_tree(parent: tk.Misc, columns: Sequence[tuple[str, str, int]], height: int = 8,
                  numeric: Iterable[str] = (), xscroll: bool = False) -> tuple[ttk.Frame, ttk.Treeview]:
    """A headings-only Treeview with scrollbars. Numeric columns are right-aligned."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, show="headings", height=height, selectmode="browse")
    configure_columns(tree, columns, numeric)
    ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ys.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    if xscroll:
        xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=xs.set)
        xs.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree


def configure_columns(tree: ttk.Treeview, columns: Sequence[tuple[str, str, int]],
                      numeric: Iterable[str] = ()) -> None:
    numeric = set(numeric)
    tree["columns"] = [c[0] for c in columns]
    for key, heading, width in columns:
        anchor = "e" if key in numeric else "w"
        tree.heading(key, text=heading, anchor=anchor)
        tree.column(key, width=width, minwidth=30, anchor=anchor, stretch=True)


def stripe(tree: ttk.Treeview, skip: Iterable[str] = ()) -> None:
    """Shade every other row. Rows carrying a tag in `skip` keep their own background."""
    skip = set(skip)
    tree.tag_configure("stripe", background=STRIPE)
    for index, iid in enumerate(tree.get_children()):
        tags = [t for t in tree.item(iid, "tags") if t != "stripe"]
        if index % 2 and not skip & set(tags):
            tags.append("stripe")
        tree.item(iid, tags=tags)


def button_row(parent: tk.Misc, specs: Sequence[tuple[str, Callable[[], None]]]) -> ttk.Frame:
    frame = ttk.Frame(parent)
    for text, command in specs:
        ttk.Button(frame, text=text, command=command).pack(side="left", padx=(0, 6))
    return frame


def open_path(path: Path) -> None:
    """Open a file or folder with the system's default program."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Form(ttk.Frame):
    """Grid of labelled inputs in one or more column groups. Values are read and written as strings."""

    def __init__(self, master: tk.Misc, columns: int = 1, **kw):
        super().__init__(master, **kw)
        self._vars: dict[str, tk.Variable] = {}
        self._labels: dict[str, str] = {}
        self._texts: dict[str, tk.Text] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self._next_row = [0] * columns

    def _place(self, key: str, label: str, widget: tk.Widget, column: int, sticky: str = "nw") -> None:
        row = self._next_row[column]
        self._next_row[column] += 1
        ttk.Label(self, text=label).grid(
            row=row, column=column * 2, sticky="nw", padx=(16 if column else 0, 6), pady=2
        )
        widget.grid(row=row, column=column * 2 + 1, sticky=sticky, pady=2)
        self._labels[key] = label.rstrip(" *")
        self.widgets[key] = widget

    def entry(self, key: str, label: str, width: int = 30, column: int = 0) -> ttk.Entry:
        var = self._vars[key] = tk.StringVar()
        widget = ttk.Entry(self, textvariable=var, width=width)
        self._place(key, label, widget, column)
        return widget

    def combo(self, key: str, label: str, values: Sequence[str], width: int = 28, column: int = 0,
              readonly: bool = True) -> ttk.Combobox:
        var = self._vars[key] = tk.StringVar()
        widget = ttk.Combobox(self, textvariable=var, width=width, values=list(values),
                              state="readonly" if readonly else "normal")
        self._place(key, label, widget, column)
        return widget

    def text(self, key: str, label: str, height: int = 3, width: int = 40, column: int = 0) -> tk.Text:
        widget = tk.Text(self, height=height, width=width, wrap="word", font="TkDefaultFont")
        self._texts[key] = widget
        self._place(key, label, widget, column, sticky="ew")
        return widget

    def custom(self, key: str, label: str, widget: tk.Widget, column: int = 0, sticky: str = "w") -> tk.Widget:
        """Place any widget created with this form as its master (e.g. a row of buttons)."""
        self._place(key, label, widget, column, sticky)
        return widget

    def add_var(self, key: str, widget: tk.Widget, var: tk.Variable) -> None:
        """Register an input placed by the caller (e.g. two entries on one row)."""
        self._vars[key] = var
        self._labels[key] = key
        self.widgets[key] = widget

    def add_text(self, key: str, widget: tk.Text) -> None:
        """Register a Text widget placed outside the grid."""
        self._texts[key] = widget
        self._labels[key] = key
        self.widgets[key] = widget

    def var(self, key: str) -> tk.Variable:
        return self._vars[key]

    def label_of(self, key: str) -> str:
        return self._labels[key]

    def get(self, key: str) -> str:
        if key in self._texts:
            return self._texts[key].get("1.0", "end-1c")
        return self._vars[key].get()

    def set(self, key: str, value) -> None:
        if key in self._texts:
            widget = self._texts[key]
            widget.delete("1.0", "end")
            widget.insert("1.0", value or "")
            return
        self._vars[key].set("" if value is None else str(value))


class EditDialog(tk.Toplevel):
    """Modal dialog with a Form and Lagre/Avbryt buttons.

    Subclasses fill self.form and implement save(); returning False keeps the dialog open.
    """

    def __init__(self, master: tk.Misc, title: str, columns: int = 1):
        super().__init__(master)
        self.title(title)
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.saved = False
        self.form = Form(self, columns=columns, padding=12)
        self.form.pack(fill="both", expand=True)
        self.extra = ttk.Frame(self, padding=(12, 0, 12, 8))  # for widgets that don't fit the form grid
        self.extra.pack(fill="both", expand=True)
        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Avbryt", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Lagre", command=self._on_save).pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        top = master.winfo_toplevel()
        self.geometry(f"+{top.winfo_rootx() + 80}+{top.winfo_rooty() + 40}")

    def show(self) -> bool:
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.saved

    def _on_save(self) -> None:
        if self.save() is False:
            return
        self.saved = True
        self.destroy()

    def save(self) -> bool | None:
        raise NotImplementedError
