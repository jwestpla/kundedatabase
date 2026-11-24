@echo off
rem Bygger Kundedatabase for Windows:
rem   dist\Kundedatabase\Kundedatabase.exe        (mappe med programmet)
rem   dist\Kundedatabase-<versjon>-windows.zip    (det du kopierer til PC-en)
rem Krever Python 3.11 eller nyere fra python.org (tcl/tk er med som standard).
setlocal
cd /d "%~dp0"

set "PY=py -3.11"
%PY% --version >nul 2>&1 || set "PY=python"
%PY% --version >nul 2>&1 || (
  echo Fant ikke Python. Installer Python 3.11 fra https://www.python.org/downloads/windows/
  exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
  %PY% -m venv .venv-build || exit /b 1
)
set "VPY=.venv-build\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip >nul || exit /b 1
"%VPY%" -m pip install -r requirements-build.txt || exit /b 1

echo === Tester ===
"%VPY%" -m pytest -q || exit /b 1

echo === PyInstaller ===
"%VPY%" -m PyInstaller --noconfirm --clean kundedatabase.spec || exit /b 1

echo === Selvtest av exe i tom datamappe ===
set "KUNDEDB_DATA=%TEMP%\kundedatabase_selvtest"
if exist "%KUNDEDB_DATA%" rmdir /s /q "%KUNDEDB_DATA%"
start "" /wait "dist\Kundedatabase\Kundedatabase.exe" --selftest
set "RC=%ERRORLEVEL%"
type "%KUNDEDB_DATA%\selftest.log"
if not "%RC%"=="0" (
  echo Selvtesten feilet.
  exit /b 1
)
set "KUNDEDB_DATA="

if not exist build mkdir build
"%VPY%" -c "import kundedb; print(kundedb.__version__)" > build\version.txt || exit /b 1
set /p VERSION=<build\version.txt
set "ZIP=dist\Kundedatabase-%VERSION%-windows.zip"
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Kundedatabase' -DestinationPath '%ZIP%'" || exit /b 1
echo.
echo Ferdig: %ZIP%
endlocal
