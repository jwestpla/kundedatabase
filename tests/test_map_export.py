import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from kundedb import map_export
from kundedb.map_export import NO_CATEGORY, build_pins, google_html, kml, leaflet_html, write_map_file
from kundedb.models import Customer

EVIL = '</script><script>alert("x")</script> & <b>'
CUSTOMERS = [
    Customer(id=1, company="Testgård AS", full_name="Kari Testesen", category="Frukt", fruit="Eple, Plomme",
             lat=59.9, lon=10.7,
             phone="91234567", email="kari@example.com", address="Testvegen 1", postcode="0150", place="Oslo"),
    Customer(id=2, full_name=EVIL, category="frukt ", lat=60.0, lon=10.8),
    Customer(id=3, company="Bærgård", category="Bær", lat=61.0, lon=7.0),
    Customer(id=4, company="Uten kat", lat=62.0, lon=8.0),
    Customer(id=5, company="Mangler Koordinater", category="Frukt"),
]


def test_pins_colours_and_missing():
    pins, missing, legend = build_pins(CUSTOMERS)
    assert [c.id for c in missing] == [5]
    assert len(pins) == 4
    by_title = {p.title: p for p in pins}
    assert by_title["Testgård AS"].colour == by_title[EVIL].colour  # 'frukt ' == 'Frukt'
    assert by_title["Bærgård"].colour != by_title["Testgård AS"].colour
    assert by_title["Uten kat"].category == NO_CATEGORY and by_title["Uten kat"].colour == map_export.NO_CATEGORY_COLOUR
    assert [label for label, _ in legend.values()] == ["Bær", "Frukt", NO_CATEGORY]
    assert by_title["Testgård AS"].name == "Kari Testesen"
    assert by_title["Testgård AS"].address == "Testvegen 1, 0150 Oslo"
    assert by_title["Testgård AS"].fruit == "Eple, Plomme"
    assert by_title["Testgård AS"].google.endswith("query=59.900000,10.700000")


def _data(html: str) -> dict:
    m = re.search(r"const DATA = (.*?);\n", html)
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_leaflet_html_is_safe_and_complete():
    pins, missing, legend = build_pins(CUSTOMERS)
    html = leaflet_html(pins, missing, legend, "osm", title="Kart <test>")
    assert "</script><script>alert" not in html  # cannot break out of the script element
    assert "<title>Kart &lt;test&gt;</title>" in html
    assert "integrity=" in html and "leaflet@1.9.4" in html
    data = _data(html)
    assert len(data["pins"]) == 4 and data["missing"] == ["Mangler Koordinater"]
    assert any(p["title"] == EVIL for p in data["pins"])  # the text is kept, just inert
    assert "innerHTML" not in html
    assert 'base["OpenStreetMap"].addTo(map)' in html


def test_google_html_uses_key_and_same_data():
    pins, missing, legend = build_pins(CUSTOMERS)
    html = google_html(pins, missing, legend, api_key="AB&C")
    assert "key=AB%26C" in html and "AdvancedMarkerElement" in html
    assert "</script><script>alert" not in html
    assert len(_data(html)["pins"]) == 4


def test_kml_is_valid_xml_with_styles():
    pins, _missing, legend = build_pins(CUSTOMERS)
    text = kml(pins, legend)
    root = ET.fromstring(text.encode("utf-8"))
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    marks = root.findall(".//k:Placemark", ns)
    assert len(marks) == 4
    assert {f.find("k:name", ns).text for f in root.findall(".//k:Folder", ns)} == {"Bær", "Frukt", NO_CATEGORY}
    names = [m.find("k:name", ns).text for m in marks]
    assert EVIL in names  # escaped in the file, read back intact
    coords = [m.find(".//k:coordinates", ns).text for m in marks]
    assert "10.700000,59.900000,0" in coords  # lon,lat
    assert "Frukt: Eple, Plomme" in text
    assert map_export._kml_colour("#1f77b4") == "ffb4771f"


def test_write_map_file_keeps_newest(tmp_path):
    for second in range(12):
        write_map_file(tmp_path, "<html></html>", datetime(2026, 1, 1, 12, 0, second))
    files = sorted(p.name for p in tmp_path.glob("kart_*.html"))
    assert len(files) == map_export.KEEP_MAP_FILES and files[-1] == "kart_20260101_120011.html"
