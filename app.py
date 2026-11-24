"""Entry point: python app.py   (packaged: Kundedatabase.exe)

    --selftest   check the installation without user interaction (database, Excel round trip, map/KML,
                 main window and dialogs);
                 writes selftest.log in the data folder and exits with 0 (OK) or 1 (error)
    --geotest    look up one public test address at Kartverket over HTTPS; writes geotest.log, exit 0/1
    --version    print the version
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

if sys.version_info < (3, 11):
    sys.exit("Kundedatabase krever Python 3.11 eller nyere.")

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    sys.exit(
        "Denne Python-installasjonen mangler tkinter. Bruk Python fra python.org, eller "
        f"installer Tk-støtte (Homebrew: brew install python-tk@{sys.version_info[0]}.{sys.version_info[1]})."
    )

from kundedb import __version__, config, db


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(__version__)
        return 0
    if "--selftest" in args:
        return selftest()
    if "--geotest" in args:
        return geo_network_test()

    paths = config.get_paths()
    try:
        config.ensure_dirs(paths)
    except OSError as exc:
        _show_fatal(f"Kunne ikke opprette datamappen\n{paths.data_dir}\n\n{exc}")
        return 1
    _setup_logging(paths)
    log = logging.getLogger("kundedatabase")
    log.info("Start versjon %s (pakket=%s), data i %s", __version__, config.is_frozen(), paths.data_dir)
    try:
        conn = db.open_database(paths.db_file, paths.backups_dir, config.BACKUP_KEEP)
    except Exception as exc:
        log.exception("Kunne ikke åpne databasen")
        _show_fatal(f"Kunne ikke åpne databasen\n{paths.db_file}\n\n{exc}")
        return 1

    from kundedb.ui.main_window import MainWindow

    window = MainWindow(conn, paths)
    try:
        window.mainloop()
    finally:
        conn.close()
    return 0


def selftest() -> int:
    """Headless check of a (packaged) installation, in a scratch database next to the real one."""
    paths = config.get_paths()
    lines = [f"Kundedatabase {__version__} selvtest", f"pakket={config.is_frozen()} python={sys.version.split()[0]}",
             f"program={sys.executable}", f"datamappe={paths.data_dir}"]
    code = 1
    try:
        config.ensure_dirs(paths)
        from kundedb import excel_io, repo
        from kundedb.models import Customer

        test_db = paths.data_dir / "selvtest.db"
        test_db.unlink(missing_ok=True)
        conn = db.connect(test_db)
        db.migrate(conn)
        c = repo.save_customer(conn, Customer(company="Selvtest AS", full_name="Test Testesen", postcode="150",
                                              kommunenr="301", org_nr="923609016", gnr_bnr="12/3"))
        xlsx = excel_io.export_customers(paths.export_dir / "selvtest.xlsx", repo.list_customers(conn))
        summary = excel_io.import_customers(conn, excel_io.read_sheet(xlsx), excel_io.MERGE)
        lines.append(f"excel: {xlsx.stat().st_size} byte, ny={summary.new} uendret={summary.unchanged}")
        if summary.unchanged != 1 or repo.get_customer(conn, c.id).postcode != "0150":
            raise RuntimeError("Excel-eksport/import gir ikke samme kunde tilbake")

        repo.save_geocode(conn, c.id, c.address_key(), 59.9, 10.75, "adresse", "selvtest")
        from kundedb import map_export

        pins, missing, legend = map_export.build_pins(repo.list_customers(conn))
        html = map_export.leaflet_html(pins, missing, legend, title="Selvtest")
        kml = map_export.kml(pins, legend)
        lines.append(f"kart: {len(pins)} pin, HTML {len(html)} tegn, KML {len(kml)} tegn")
        from kundedb.ui.export_dialog import ExportDialog
        from kundedb.ui.main_window import MainWindow
        from kundedb.ui.settings_dialog import SettingsDialog

        window = MainWindow(conn, paths)
        window.update()
        window.toggle_filters()
        window.update()
        for dialog in (ExportDialog(window), SettingsDialog(window, conn)):
            dialog.update()
            dialog.destroy()
        lines.append(f"vindu: {window.title()} – {len(window.customers)} kunde(r) vist")
        window.destroy()
        conn.close()
        test_db.unlink(missing_ok=True)
        xlsx.unlink(missing_ok=True)
        lines.append("OK")
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("FEIL")
    return _write_log(paths, "selftest.log", lines, code)


def geo_network_test() -> int:
    """Reach Kartverket over HTTPS with a public test address (needs internet; not part of --selftest)."""
    from kundedb.geocode import Geocoder
    from kundedb.models import Customer

    paths = config.get_paths()
    lines = [f"Kundedatabase {__version__} geotest"]
    code = 1
    try:
        result = Geocoder().geocode(Customer(address="Karl Johans gate 1", postcode="0154"))
        lines.append(f"{result.source}: {result.lat}, {result.lon} – {result.note}")
        code = 0 if result.found else 1
    except Exception as exc:  # noqa: BLE001
        lines.append(f"{type(exc).__name__}: {exc}")
    lines.append("OK" if code == 0 else "FEIL")
    return _write_log(paths, "geotest.log", lines, code)


def _write_log(paths: config.Paths, name: str, lines: list[str], code: int) -> int:
    text = "\n".join(lines) + "\n"
    try:
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        (paths.data_dir / name).write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        print(text, end="")
    return code


def _setup_logging(paths: config.Paths) -> None:
    handler = RotatingFileHandler(paths.log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # A windowed exe has no console: give print/tracebacks somewhere harmless to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    sys.excepthook = lambda *exc: logging.getLogger("kundedatabase").critical("Ufanget feil", exc_info=exc)


def _show_fatal(message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Kundedatabase", message, parent=root)
    root.destroy()


if __name__ == "__main__":
    sys.exit(main())
