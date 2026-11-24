# PyInstaller build for Kundedatabase (one-folder: dist/Kundedatabase/Kundedatabase.exe).
#
#   pyinstaller --noconfirm --clean kundedatabase.spec
#
# One-folder rather than one-file: starts faster, no unpacking to %TEMP% on every start, and fewer
# antivirus false alarms. No data files are bundled: the database lives in %APPDATA%\Kundedatabase.
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    datas=[],
    excludes=["pytest", "_pytest", "PyInstaller", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kundedatabase",
    console=sys.platform != "win32",  # windowed on Windows; console elsewhere so --selftest prints
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Kundedatabase", upx=False)
