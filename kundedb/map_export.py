"""Maps of a selection of customers: a local HTML map (Leaflet, or Google Maps JS with an API key) and KML
for Google My Maps. Pure: returns text; the UI writes the file and opens the browser.

Customer data goes into the page as JSON (with "</" escaped) and popups are built with textContent, so
names and notes can never inject HTML or script. The page needs internet for the map library and tiles.
Verified Nov 2026: Kartverket topo tiles https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/
{z}/{y}/{x}.png (from WMTSCapabilities), OpenStreetMap standard tiles, Leaflet 1.9.4 with SRI hashes.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from .geocode import google_maps_url
from .models import Customer

BACKGROUNDS: dict[str, str] = {"kartverket": "Kartverket topografisk kart", "osm": "OpenStreetMap"}
TILES = {
    "kartverket": ("https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png",
                   "&copy; <a href=\"https://www.kartverket.no/\">Kartverket</a>", 18),
    "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>-bidragsytere", 19),
}
LEAFLET_JS = ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=")
LEAFLET_CSS = ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=")
GOOGLE_JS = "https://maps.googleapis.com/maps/api/js"

# Distinct colours, readable as pin fills; the first categories get the strongest ones.
PALETTE = ("#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22",
           "#393b79", "#ad494a", "#637939")
NO_CATEGORY = "Uten kategori"
NO_CATEGORY_COLOUR = "#7f7f7f"
MAP_FILE_PREFIX = "kart_"
KEEP_MAP_FILES = 10


@dataclass
class Pin:
    lat: float
    lon: float
    category: str
    colour: str
    title: str
    name: str
    phone: str
    email: str
    address: str
    google: str


def _category(c: Customer) -> tuple[str, str]:
    """(key for colouring, label). 'frukt ' and 'Frukt' share a colour."""
    label = " ".join((c.category or "").split())
    return (label.casefold(), label) if label else ("", NO_CATEGORY)


def category_colours(customers: list[Customer]) -> dict[str, tuple[str, str]]:
    """category key -> (label, colour), in alphabetical order; no category is grey and last."""
    labels: dict[str, str] = {}
    for c in customers:
        key, label = _category(c)
        labels.setdefault(key, label)
    keys = sorted((k for k in labels if k), key=str.casefold)
    result = {k: (labels[k], PALETTE[i % len(PALETTE)]) for i, k in enumerate(keys)}
    if "" in labels:
        result[""] = (NO_CATEGORY, NO_CATEGORY_COLOUR)
    return result


def build_pins(customers: list[Customer]) -> tuple[list[Pin], list[Customer], dict[str, tuple[str, str]]]:
    """Pins for customers with coordinates, the customers without, and the legend (key -> label, colour)."""
    with_coords = [c for c in customers if c.has_coordinates]
    missing = [c for c in customers if not c.has_coordinates]
    legend = category_colours(with_coords)
    pins = []
    for c in with_coords:
        key, _label = _category(c)
        label, colour = legend[key]
        town = " ".join(filter(None, (c.postcode, c.place)))
        pins.append(Pin(lat=c.lat, lon=c.lon, category=label, colour=colour,  # type: ignore[arg-type]
                        title=c.company or c.full_name or "", name=c.full_name if c.company else "",  # type: ignore[arg-type]
                        phone=c.phone or "", email=c.email or "",
                        address=", ".join(filter(None, (c.address, town))), google=google_maps_url(c) or ""))
    return pins, missing, legend


def _json(data) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _common(title: str, pins: list[Pin], missing: list[Customer], legend: dict[str, tuple[str, str]]) -> dict:
    return {
        "title": title,
        "pins": [asdict(p) for p in pins],
        "missing": [c.display_name for c in missing],
        "legend": [[label, colour] for label, colour in legend.values()],
    }


_STYLE = """
html, body { height: 100%; margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
#map { position: absolute; top: 0; bottom: 0; left: 0; right: 0; }
.box { background: #fff; padding: 8px 10px; border-radius: 6px; box-shadow: 0 1px 5px rgba(0,0,0,.35);
       font-size: 13px; line-height: 1.4; max-width: 320px; }
.box h1 { font-size: 15px; margin: 0 0 4px; }
.legend span.dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px;
                   vertical-align: -1px; border: 1px solid #333; }
.missing { color: #8a4b00; margin-top: 6px; }
.missing ul { margin: 4px 0 0; padding-left: 18px; max-height: 160px; overflow: auto; }
.popup b { font-size: 14px; }
.popup a { display: inline-block; margin-top: 6px; }
#panel { position: absolute; top: 10px; left: 54px; z-index: 1000; }
#legend { position: absolute; bottom: 24px; right: 10px; z-index: 1000; }
"""

# Shared by both map kinds: builds the info panel, the legend and popup content with textContent only.
_SHARED_JS = """
function el(tag, text, cls) { const e = document.createElement(tag); if (text) e.textContent = text;
  if (cls) e.className = cls; return e; }
function popup(p) {
  const d = el('div', null, 'popup');
  d.appendChild(el('b', p.title));
  for (const line of [p.name, p.address, p.phone ? 'Tlf. ' + p.phone : '']) if (line) d.appendChild(el('div', line));
  if (p.email) { const a = el('a', p.email); a.href = 'mailto:' + p.email; d.appendChild(el('div')).appendChild(a); }
  d.appendChild(el('div', p.category));
  if (p.google) { const a = el('a', 'Åpne i Google Maps'); a.href = p.google; a.target = '_blank';
    a.rel = 'noopener'; d.appendChild(a); }
  return d;
}
function panels() {
  const panel = document.getElementById('panel');
  panel.appendChild(el('h1', DATA.title));
  panel.appendChild(el('div', DATA.pins.length + ' kunde(r) i kartet.'));
  if (DATA.missing.length) {
    const m = el('div', null, 'missing');
    m.appendChild(el('div', '⚠ ' + DATA.missing.length + ' kunde(r) mangler koordinater og er ikke med:'));
    const ul = el('ul'); for (const name of DATA.missing) ul.appendChild(el('li', name)); m.appendChild(ul);
    panel.appendChild(m);
  }
  const legend = document.getElementById('legend');
  for (const [label, colour] of DATA.legend) {
    const row = el('div'); const dot = el('span', null, 'dot'); dot.style.background = colour;
    row.appendChild(dot); row.appendChild(document.createTextNode(label)); legend.appendChild(row);
  }
}
"""


def _page(title: str, head: str, body_script: str) -> str:
    return f"""<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{escape(title)}</title>
{head}
<style>{_STYLE}</style>
</head>
<body>
<div id="map"></div>
<div id="panel" class="box"></div>
<div id="legend" class="box legend"></div>
<script>
{body_script}
</script>
</body>
</html>
"""


def leaflet_html(pins: list[Pin], missing: list[Customer], legend: dict[str, tuple[str, str]],
                 background: str = "kartverket", title: str = "Kundekart") -> str:
    data = _common(title, pins, missing, legend)
    layers = {BACKGROUNDS[k]: {"url": url, "attribution": attr, "maxZoom": zoom} for k, (url, attr, zoom) in TILES.items()}
    first = BACKGROUNDS.get(background, BACKGROUNDS["kartverket"])
    head = (f'<link rel="stylesheet" href="{LEAFLET_CSS[0]}" integrity="{LEAFLET_CSS[1]}" crossorigin="">\n'
            f'<script src="{LEAFLET_JS[0]}" integrity="{LEAFLET_JS[1]}" crossorigin=""></script>')
    script = f"""const DATA = {_json(data)};
const LAYERS = {_json(layers)};
{_SHARED_JS}
const map = L.map('map');
const base = {{}};
for (const [name, t] of Object.entries(LAYERS)) base[name] = L.tileLayer(t.url, {{attribution: t.attribution, maxZoom: t.maxZoom}});
base[{_json(first)}].addTo(map);
L.control.layers(base, null, {{position: 'topright'}}).addTo(map);
const markers = DATA.pins.map(p => L.circleMarker([p.lat, p.lon], {{radius: 8, color: '#222', weight: 1,
  fillColor: p.colour, fillOpacity: 0.9}}).bindPopup(popup(p)).bindTooltip(p.title).addTo(map));
if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.15), {{maxZoom: 14}});
else map.setView([64.5, 12.0], 5);
panels();
"""
    return _page(title, head, script)


def google_html(pins: list[Pin], missing: list[Customer], legend: dict[str, tuple[str, str]], api_key: str,
                title: str = "Kundekart") -> str:
    """Google Maps JS API (AdvancedMarkerElement with coloured pins). Needs a key with Maps JavaScript API."""
    data = _common(title, pins, missing, legend)
    src = GOOGLE_JS + "?" + urlencode({"key": api_key, "callback": "initMap", "libraries": "marker", "v": "weekly",
                                       "loading": "async"})
    head = f'<script async src="{escape(src)}"></script>'
    script = f"""const DATA = {_json(data)};
{_SHARED_JS}
async function initMap() {{
  const {{Map, InfoWindow}} = await google.maps.importLibrary('maps');
  const {{AdvancedMarkerElement, PinElement}} = await google.maps.importLibrary('marker');
  const map = new Map(document.getElementById('map'), {{center: {{lat: 64.5, lng: 12.0}}, zoom: 5,
    mapId: 'DEMO_MAP_ID', mapTypeControl: true}});
  const info = new InfoWindow();
  const bounds = new google.maps.LatLngBounds();
  for (const p of DATA.pins) {{
    const pin = new PinElement({{background: p.colour, borderColor: '#222', glyphColor: '#fff'}});
    const marker = new AdvancedMarkerElement({{map, position: {{lat: p.lat, lng: p.lon}}, content: pin.element,
      title: p.title}});
    marker.addListener('click', () => {{ info.setContent(popup(p)); info.open({{map, anchor: marker}}); }});
    bounds.extend({{lat: p.lat, lng: p.lon}});
  }}
  if (DATA.pins.length) {{ map.fitBounds(bounds, 60); if (DATA.pins.length === 1) map.setZoom(14); }}
}}
window.initMap = initMap;
panels();
"""
    return _page(title, head, script)


def _kml_colour(hex_colour: str) -> str:
    """'#1f77b4' -> KML 'ffb4771f' (aabbggrr)."""
    r, g, b = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"ff{b}{g}{r}"


def kml(pins: list[Pin], legend: dict[str, tuple[str, str]], title: str = "Kunder") -> str:
    """KML 2.2 for Google My Maps / Google Earth: one style and folder per category."""
    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}kml")
    doc = ET.SubElement(root, f"{{{ns}}}Document")
    ET.SubElement(doc, f"{{{ns}}}name").text = title
    style_ids = {}
    for i, (label, colour) in enumerate(legend.values()):
        style_id = f"kategori{i}"
        style_ids[label] = style_id
        style = ET.SubElement(doc, f"{{{ns}}}Style", id=style_id)
        icon_style = ET.SubElement(style, f"{{{ns}}}IconStyle")
        ET.SubElement(icon_style, f"{{{ns}}}color").text = _kml_colour(colour)
        icon = ET.SubElement(icon_style, f"{{{ns}}}Icon")
        ET.SubElement(icon, f"{{{ns}}}href").text = "https://maps.google.com/mapfiles/kml/paddle/wht-blank.png"
    folders = {}
    for label in style_ids:
        folder = folders[label] = ET.SubElement(doc, f"{{{ns}}}Folder")
        ET.SubElement(folder, f"{{{ns}}}name").text = label
    for p in pins:
        mark = ET.SubElement(folders[p.category], f"{{{ns}}}Placemark")
        ET.SubElement(mark, f"{{{ns}}}name").text = p.title
        lines = [p.name, p.address, f"Tlf. {p.phone}" if p.phone else "", p.email, p.category]
        ET.SubElement(mark, f"{{{ns}}}description").text = "\n".join(line for line in lines if line)
        ET.SubElement(mark, f"{{{ns}}}styleUrl").text = f"#{style_ids[p.category]}"
        extended = ET.SubElement(mark, f"{{{ns}}}ExtendedData")
        for name, value in (("Fullt navn", p.name), ("Adresse", p.address), ("Telefon", p.phone),
                            ("E-post", p.email), ("Kategori", p.category)):
            data = ET.SubElement(extended, f"{{{ns}}}Data", name=name)
            ET.SubElement(data, f"{{{ns}}}value").text = value
        point = ET.SubElement(mark, f"{{{ns}}}Point")
        ET.SubElement(point, f"{{{ns}}}coordinates").text = f"{p.lon:.6f},{p.lat:.6f},0"
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def map_title(count: int, when: datetime | None = None) -> str:
    return f"Kundekart – {count} kunde(r), {(when or datetime.now()):%d.%m.%Y %H:%M}"


def write_map_file(export_dir: Path, html: str, when: datetime | None = None) -> Path:
    """Write kart_<timestamp>.html and keep only the newest KEEP_MAP_FILES map files."""
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{MAP_FILE_PREFIX}{(when or datetime.now()):%Y%m%d_%H%M%S}.html"
    path.write_text(html, encoding="utf-8")
    old = sorted(export_dir.glob(f"{MAP_FILE_PREFIX}*.html"))
    for f in old[: max(len(old) - KEEP_MAP_FILES, 0)]:
        f.unlink(missing_ok=True)
    return path
