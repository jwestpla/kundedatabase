# Kundedatabase

Customer register for an agricultural advisor (replaces an Excel sheet). Standalone app, styled and structured
like Gjødselplan (github.com/jwestpla/gjodselplan, local copy ~/Documents/gjodselplan_test); no domain logic
is shared. UI in Norwegian bokmål; code, comments and identifiers in English.

## Status
- v0.1.0: all 9 spec features built: import, CRUD, list/detail, ☑ selection, criteria, geocoding,
  Google Maps, selection map + KML, Excel export. The user approved the plan (stages A–E) on 2026-11-24.
  Features 1–7 were built before the plan was approved, because the first paste of the spec was cut off.
- Sharing: public repo jwestpla/kundedatabase, the same set-up as Gjødselplan. Download page docs/index.html on
  GitHub Pages (main, /docs). Pushing a v* tag runs Windows-bygg and publishes a Release with
  Kundedatabase-windows.zip (fixed asset name; the page links to releases/latest/download/...).
  The tag must match kundedb.__version__.
- Frukt (fruit) column added on the user's request (migration 3, 2026-11-24).
- Not verified: the Google Maps JS variant of the map (needs a real API key); the Windows build.

## Environment
- `.venv` = python.org 3.11 (has tkinter) + openpyxl + pytest. Homebrew python3 has no `_tkinter`.
- `.venv/bin/python -m pytest`, `.venv/bin/python app.py [--selftest|--geotest]`.
- Never commit customer data: `data/`, `*.db`, `*.xlsx`, `*.kml`, `kart_*.html`, `sample/` are gitignored.
  Tests and development use FAKE data only: `tools/make_sample_xlsx.py` (synthetic mod11-valid org.nr starting
  with 8, invented names; real postnummer/kommunenr so geocoding can be tried).
- Never take screenshots of the whole screen (it can show the user's private windows). Check layout with
  winfo_* geometry. Stub webbrowser/open_path/messagebox in UI scripts, so nothing opens on the user's screen.

## Architecture
- `models.py`: `Customer`, `FIELD_LABELS` (= exact Excel headers, in Excel order; «Frukt» is the 12th, after the
  user's original 11), `FRUITS` (Eple, Pære, Plomme, Kirsebær), `LIST_FIELDS`, `GEOCODE_SOURCES`.
- `validation.py` (pure): cleaning (`cell_text`, `pad4`, `normalize`), gnr/bnr parsing, `warnings()`.
  Validation only warns; nothing blocks saving.
- `repo.py`: all SQL. `save_customer` normalises, clears auto coordinates when an address field changes
  (keeps 'manuell'), and doesn't bump `updated` when nothing changed. `save_geocode` refuses stale results
  (address changed meanwhile), manual coordinates (unless `replace_manual`), and never erases coordinates on
  "not found".
- `excel_io.py`: header detection (first 10 rows, `normalize_header` + aliases), import in one transaction,
  export with text cells. `filters.py` (pure): search + criteria + named filters JSON.
- `geocode.py`: `Geocoder` (network, injectable getter, `RateLimiter`), `google_maps_url`, `parse_coordinates`.
- `map_export.py` (pure): pins + category colours, Leaflet HTML (Kartverket topo / OSM layers, Leaflet 1.9.4
  with SRI), Google Maps JS HTML (AdvancedMarkerElement, when `google_maps_api_key` is set), KML. Data goes in as
  JSON with `</` escaped, and popups are built with textContent (no innerHTML). Files: `<data>/export/kart_*.html`
  (10 kept).
- Settings: `setting` table (migration 2): `map_background` ('kartverket' | 'osm'), `google_maps_api_key`.
- `ui/`: `export_dialog` (☑ / visible / all, optional coordinate and notes columns), `settings_dialog`;
  `main_window` holds all customers in memory and the `checked` id set; `customer_list` (Treeview,
  checkbox column #1), `detail_panel`, `customer_dialog`, `import_dialog`, `filter_panel`, `geocode_dialog`
  (worker thread does network only; the main thread writes SQLite via a queue; cyclic GC off while it runs, as in
  Gjødselplan).
- Schema: migrations in `db.MIGRATIONS` (append only). Ask before changing the schema.

## Decisions (where the spec was silent)
- Merge: empty cells in the file never erase stored values; columns not in the file are untouched. The
  Firma + Fullt navn fallback only matches customers without a different Org.nr. Ambiguous matches are row errors.
  Replace = delete all, then the same merge (duplicate rows in the file become one customer).
- "Hoppet over" in the summary = unchanged rows + rows without Firma and Fullt navn.
- Org.nr is stored compacted to digits when it is only digits plus separators. Phone is stored as written.
- Gnr og bnr: comma/semicolon/"og" separated; "12/3", "12/3/0", "12-3", "gnr 12 bnr 3", "4642-12/3" (kommunenr
  in front). `gnr`/`bnr` columns hold the first one; geocoding tries each in turn.
- Geocode fallback c): postnummer = median of up to 1000 address points (no official centroid API); without a
  postnummer, Stedsnavn API (`knr` filter when Kommunenr is valid). Both are stored as source 'postnummer'.
- A failed lookup is stored (geocode_date + geocode_note, no coordinates) so batches don't retry it. There is a
  separate menu item for retrying these.
- "X valgt av Y": Y = all customers. Velg alle treff / Legg treff til utvalg use criteria over all customers
  (not limited by the quick search). Inverter works on visible rows only.
- Frukt: several values, stored canonically as "Eple, Plomme" (FRUITS order). `validation.split_fruit` reads
  plurals, "og"/"/"/";", moreller → Kirsebær and English names. Unknown words are kept as written, after the known
  ones, with a warning. Filters treat it as a set (see filters.py docstring): en av = any of, er ikke = none of,
  er lik = exactly, inneholder = has (or substring). An import without the column leaves stored fruit untouched.
  The dialog has checkboxes plus an «annen frukt» entry.
- Map and KML use the ☑ customers; with none checked, the app offers the visible list. Customers without
  coordinates are listed in a warning before the map opens, and on the map itself.
- "Gjeldende filtertreff" in the export dialog = the rows shown in the list (search + criteria when
  "Vis bare treff" is on).
- Entry point is `app.py` (Gjødselplan convention), not `main.py`.
- Detail panel buttons sit at the top so they stay visible on a 1366×768 laptop at 125 % (Tk ≈ 1093×614).
