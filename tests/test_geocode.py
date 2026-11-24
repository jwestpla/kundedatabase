import json
from urllib.parse import parse_qs, urlsplit

import pytest

from kundedb import geocode
from kundedb.geocode import (
    Geocoder, GeocodeUnavailable, RateLimiter, google_maps_url, parse_coordinates,
)
from kundedb.models import Customer


class FakeNet:
    """Answers like Kartverket's APIs from a table of made-up data; records the calls."""

    def __init__(self, eiendom=None, adresser=None, fuzzy=None, postnummer=None, stedsnavn=None):
        self.eiendom = eiendom or {}  # (knr, gnr, bnr, fnr) -> [(lon, lat, hovedområde)]
        self.adresser = adresser or {}  # (sok, postnummer) -> (lat, lon)
        self.fuzzy = fuzzy or {}
        self.postnummer = postnummer or {}  # postnummer -> [(lat, lon)]
        self.stedsnavn = stedsnavn or {}  # sok -> (nord, øst)
        self.calls = []

    def __call__(self, url):
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}{parts.path}"
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.calls.append((base, q))
        assert q.get("utkoordsys") == "4258"
        if base == geocode.EIENDOM_URL:
            key = (q["kommunenummer"], int(q["gardsnummer"]), int(q["bruksnummer"]), int(q["festenummer"]))
            feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {"hovedområde": main}} for lon, lat, main in self.eiendom.get(key, [])]
            return json.dumps({"type": "FeatureCollection", "features": feats}).encode()
        if base == geocode.ADRESSE_URL:
            if "sok" not in q:
                pts = self.postnummer.get(q["postnummer"], [])
                return json.dumps({"adresser": [{"representasjonspunkt": {"lat": a, "lon": b}} for a, b in pts]}).encode()
            table = self.fuzzy if q.get("fuzzy") == "true" else self.adresser
            hit = table.get((q["sok"], q.get("postnummer")))
            adresser = [{"adressetekst": q["sok"], "postnummer": q.get("postnummer"), "poststed": "STED",
                         "representasjonspunkt": {"epsg": "EPSG:4258", "lat": hit[0], "lon": hit[1]}}] if hit else []
            return json.dumps({"adresser": adresser}).encode()
        if base == geocode.STEDSNAVN_URL:
            hit = self.stedsnavn.get(q["sok"])
            navn = [{"navneobjekttype": "Tettsted", "representasjonspunkt": {"nord": hit[0], "øst": hit[1]}}] if hit else []
            return json.dumps({"navn": navn}).encode()
        raise AssertionError(url)


def coder(net):
    return Geocoder(net, RateLimiter(0))


def test_matrikkel_first_and_main_teig():
    net = FakeNet(eiendom={("3218", 12, 3, 0): [(10.1, 59.1, False), (10.2, 59.2, True)]},
                  adresser={("Gardsvegen 1", "1430"): (59.5, 10.5)})
    r = coder(net).geocode(Customer(kommunenr="3218", gnr_bnr="12/3", address="Gardsvegen 1", postcode="1430"))
    assert (r.lat, r.lon, r.source) == (59.2, 10.2, "gnr_bnr")
    assert len(net.calls) == 1


def test_second_property_and_kommunenr_in_text():
    net = FakeNet(eiendom={("4642", 14, 1, 0): [(7.0, 61.0, True)]})
    r = coder(net).geocode(Customer(kommunenr="4640", gnr_bnr="12/3, 4642-14/1"))
    assert r.source == "gnr_bnr" and r.lat == 61.0
    assert [c[1]["kommunenummer"] for c in net.calls] == ["4640", "4642"]


def test_falls_back_to_address_then_fuzzy():
    net = FakeNet(fuzzy={("Gardsvegen 1", "1430"): (59.5, 10.5)})
    r = coder(net).geocode(Customer(kommunenr="3218", gnr_bnr="12/3", address="Gardsvegen 1", postcode="1430"))
    assert (r.lat, r.source) == (59.5, "adresse")
    assert "omtrentlig" in r.note


def test_postcode_median():
    net = FakeNet(postnummer={"1430": [(59.0, 10.0), (59.6, 10.6), (59.7, 30.0)]})
    r = coder(net).geocode(Customer(address="Ukjent 9", postcode="1430"))
    assert (r.lat, r.lon, r.source) == (59.6, 10.6, "postnummer")
    assert "3 adresser" in r.note


def test_place_when_no_postcode():
    net = FakeNet(stedsnavn={"Ås": (59.66, 10.79)})
    r = coder(net).geocode(Customer(place="Ås", kommunenr="3218"))
    assert (r.lat, r.source) == (59.66, "postnummer")
    assert net.calls[-1][1]["knr"] == "3218"


def test_not_found_and_nothing_to_look_up():
    r = coder(FakeNet()).geocode(Customer(gnr_bnr="12/3", postcode="1430"))
    assert not r.found and "gnr/bnr uten kommunenr" in r.note and "postnummer 1430" in r.note
    net = FakeNet()
    r = coder(net).geocode(Customer(company="x"))
    assert not r.found and "mangler" in r.note and net.calls == []


def test_network_error_propagates():
    def offline(url):
        raise GeocodeUnavailable("Fikk ikke kontakt")
    with pytest.raises(GeocodeUnavailable):
        coder(offline).geocode(Customer(address="x", postcode="1430"))


def test_bad_json_is_unavailable():
    with pytest.raises(GeocodeUnavailable):
        coder(lambda url: b"<html>").geocode(Customer(postcode="1430"))


def test_rate_limiter():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 3))
        t[0] += s

    limiter = RateLimiter(4, clock=lambda: t[0], sleep=sleep)
    for _ in range(3):
        limiter.wait()
    assert slept == [0.25, 0.25]


def test_google_maps_url():
    assert google_maps_url(Customer(lat=59.661938, lon=10.79229)) == \
        "https://www.google.com/maps/search/?api=1&query=59.661938,10.792290"
    url = google_maps_url(Customer(address="Gardsvegen 1", postcode="1430", place="Ås"))
    assert url.endswith("query=Gardsvegen%201%2C%201430%20%C3%85s%2C%20Norge")
    assert google_maps_url(Customer(company="x")) is None


@pytest.mark.parametrize("text, expected", [
    ("59.661938, 10.79229", (59.661938, 10.79229)),
    ("59,661938 10,79229", (59.661938, 10.79229)),
    ("59.66;10.79", (59.66, 10.79)),
    ("https://www.google.com/maps/@59.66,10.79,15z", (59.66, 10.79)),
    ("https://www.google.com/maps/place/x/data=!3d59.7!4d10.8", (59.7, 10.8)),
    ("59,66", None),
    ("hei", None),
    ("95.0, 10.0", None),
])
def test_parse_coordinates(text, expected):
    assert parse_coordinates(text) == expected
