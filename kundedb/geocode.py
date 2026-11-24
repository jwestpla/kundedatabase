"""Coordinates for customers from Kartverket's open APIs (no key, no login), plus Google Maps links.

Priority (verified against the APIs' OpenAPI descriptions, Nov 2026):
  a) Kommunenr + gnr/bnr: Eiendom API  GET https://api.kartverket.no/eiendom/v1/geokoding
     ?kommunenummer&gardsnummer&bruksnummer&festenummer&utkoordsys=4258 -> one point per teig; the
     teig marked "hovedområde" is used. Best for farms.
  b) Adresse 1 + Postnummer: Adresse API  GET https://ws.geonorge.no/adresser/v1/sok
     ?sok&postnummer&utkoordsys=4258 -> representasjonspunkt; retried with fuzzy=true.
  c) Postnummer: the median of the address points in the postcode (same API, up to 1000 addresses);
     without a postnummer, Sted via the Stedsnavn API GET https://api.kartverket.no/stedsnavn/v1/navn.

Only the address fields are sent. EPSG:4258 (EUREF89) and WGS84 differ by under a metre in Norway.
Network code only runs in Geocoder; everything else here is pure.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import statistics
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .models import Customer
from .validation import is_four_digits, parse_gnr_bnr

EIENDOM_URL = "https://api.kartverket.no/eiendom/v1/geokoding"
ADRESSE_URL = "https://ws.geonorge.no/adresser/v1/sok"
STEDSNAVN_URL = "https://api.kartverket.no/stedsnavn/v1/navn"
EPSG = 4258

TIMEOUT_S = 20
REQUESTS_PER_SECOND = 4  # politeness limit towards Kartverket (shared by all lookups)
POSTCODE_SAMPLE = 1000

Getter = Callable[[str], bytes]  # url -> body


class GeocodeUnavailable(Exception):
    """The service could not be reached (offline, server error). Norwegian message for the user."""


@dataclass
class GeocodeResult:
    lat: float | None
    lon: float | None
    source: str | None  # 'gnr_bnr' | 'adresse' | 'postnummer' | None (not found)
    note: str

    @property
    def found(self) -> bool:
        return self.lat is not None


# --- HTTP ----------------------------------------------------------------------------------------

# python.org Python on macOS ships without a CA store until "Install Certificates" is run.
_SYSTEM_CA_FILES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")
_ssl_context: ssl.SSLContext | None = None


def _context() -> ssl.SSLContext:
    global _ssl_context
    if _ssl_context is None:
        context = ssl.create_default_context()
        if not context.cert_store_stats().get("x509_ca"):
            for ca_file in _SYSTEM_CA_FILES:
                if Path(ca_file).is_file():
                    context.load_verify_locations(ca_file)
                    break
        _ssl_context = context
    return _ssl_context


def http_get(url: str) -> bytes:
    """Body of a GET. 4xx (except 429) gives b'' (= nothing found); other problems raise GeocodeUnavailable."""
    host = urlsplit(url).hostname or url
    request = Request(url, headers={"User-Agent": f"Kundedatabase/{__version__}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_S, context=_context()) as response:
            return response.read()
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code != 429:
            return b""
        raise GeocodeUnavailable(f"{host} svarte med feil {exc.code}. Prøv igjen senere.") from exc
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise GeocodeUnavailable(f"Den sikre forbindelsen til {host} kunne ikke bekreftes (sertifikatfeil). "
                                     "Et nettverk med filter eller proxy kan gi dette.") from exc
        raise GeocodeUnavailable(f"Fikk ikke kontakt med {host} ({exc.reason}). Oppslag krever internett.") from exc
    except (socket.timeout, TimeoutError, ConnectionError) as exc:
        raise GeocodeUnavailable(f"Fikk ikke kontakt med {host} ({exc}). Oppslag krever internett.") from exc


class RateLimiter:
    """At most `per_second` calls to wait() per second, across threads."""

    def __init__(self, per_second: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self.clock, self.sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            self.sleep(delay)


# --- Lookups ------------------------------------------------------------------------------------


def _point(rep: dict | None) -> tuple[float, float] | None:
    if not isinstance(rep, dict):
        return None
    lat = rep.get("lat", rep.get("nord"))
    lon = rep.get("lon", rep.get("øst"))
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


class Geocoder:
    def __init__(self, getter: Getter = http_get, limiter: RateLimiter | None = None):
        self.getter = getter
        self.limiter = limiter or RateLimiter(REQUESTS_PER_SECOND)

    def _json(self, url: str, params: dict) -> dict:
        self.limiter.wait()
        body = self.getter(url + "?" + urlencode(params))
        if not body:
            return {}
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise GeocodeUnavailable(f"Uventet svar fra {urlsplit(url).hostname}. Prøv igjen senere.") from exc
        return data if isinstance(data, dict) else {}

    def by_matrikkel(self, kommunenr: str, gnr: int, bnr: int, fnr: int = 0) -> tuple[float, float] | None:
        data = self._json(EIENDOM_URL, {"kommunenummer": kommunenr, "gardsnummer": gnr, "bruksnummer": bnr,
                                        "festenummer": fnr, "utkoordsys": EPSG})
        features = [f for f in data.get("features") or [] if isinstance(f, dict)]
        features.sort(key=lambda f: not (f.get("properties") or {}).get("hovedområde"))
        for f in features:
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if len(coords) >= 2:
                return float(coords[1]), float(coords[0])  # GeoJSON is lon, lat
        return None

    def by_address(self, address: str, postcode: str | None = None, place: str | None = None,
                   kommunenr: str | None = None) -> tuple[tuple[float, float], str, bool] | None:
        """(point, address text found, fuzzy?) for a street/farm address within a postcode, kommune or place."""
        params: dict = {"sok": address, "treffPerSide": 5, "utkoordsys": EPSG}
        if postcode:
            params["postnummer"] = postcode
        elif kommunenr:
            params["kommunenummer"] = kommunenr
        elif place:
            params["poststed"] = place
        else:
            return None
        for fuzzy in (False, True):
            data = self._json(ADRESSE_URL, {**params, "fuzzy": "true"} if fuzzy else params)
            for hit in data.get("adresser") or []:
                point = _point(hit.get("representasjonspunkt"))
                if point:
                    text = f"{hit.get('adressetekst', '')}, {hit.get('postnummer', '')} {hit.get('poststed', '')}"
                    return point, text.strip(" ,"), fuzzy
        return None

    def by_postcode(self, postcode: str) -> tuple[tuple[float, float], int] | None:
        """Median of the address points in the postcode, and how many addresses it is based on."""
        data = self._json(ADRESSE_URL, {"postnummer": postcode, "treffPerSide": POSTCODE_SAMPLE, "utkoordsys": EPSG,
                                        "filtrer": "adresser.representasjonspunkt"})
        points = [p for p in (_point(a.get("representasjonspunkt")) for a in data.get("adresser") or []) if p]
        if not points:
            return None
        return (statistics.median(p[0] for p in points), statistics.median(p[1] for p in points)), len(points)

    def by_place(self, place: str, kommunenr: str | None = None) -> tuple[tuple[float, float], str] | None:
        params: dict = {"sok": place, "fuzzy": "false", "treffPerSide": 1, "utkoordsys": EPSG}
        if kommunenr:
            params["knr"] = kommunenr
        data = self._json(STEDSNAVN_URL, params)
        for hit in data.get("navn") or []:
            point = _point(hit.get("representasjonspunkt"))
            if point:
                return point, str(hit.get("navneobjekttype") or "stedsnavn").lower()
        return None

    def geocode(self, c: Customer) -> GeocodeResult:
        """Look up one customer in priority order. Raises GeocodeUnavailable when offline."""
        knr = c.kommunenr if is_four_digits(c.kommunenr) else None
        postcode = c.postcode if is_four_digits(c.postcode) else None
        tried: list[str] = []

        for m in parse_gnr_bnr(c.gnr_bnr):
            m_knr = m.kommunenr or knr
            if not m_knr:
                tried.append("gnr/bnr uten kommunenr")
                break
            point = self.by_matrikkel(m_knr, m.gnr, m.bnr, m.fnr)
            if point:
                return GeocodeResult(*point, "gnr_bnr", f"Eiendom {m_knr}-{m.gnr}/{m.bnr}/{m.fnr} (Kartverket)")
            tried.append(f"eiendom {m_knr}-{m.gnr}/{m.bnr}/{m.fnr} ikke funnet")

        if c.address:
            found = self.by_address(c.address, postcode, c.place, knr)
            if found:
                point, text, fuzzy = found
                return GeocodeResult(*point, "adresse", f"Adresse {text}" + (" (omtrentlig treff)" if fuzzy else ""))
            tried.append("adressen ikke funnet")

        if postcode:
            found_pc = self.by_postcode(postcode)
            if found_pc:
                point, n = found_pc
                return GeocodeResult(*point, "postnummer", f"Midt i postnummer {postcode} ({n} adresser) – omtrentlig")
            tried.append(f"postnummer {postcode} ikke funnet")
        elif c.place:
            found_place = self.by_place(c.place, knr)
            if found_place:
                point, kind = found_place
                return GeocodeResult(*point, "postnummer", f"Stedsnavn «{c.place}» ({kind}) – omtrentlig")
            tried.append(f"stedsnavn «{c.place}» ikke funnet")

        if not tried:
            return GeocodeResult(None, None, None, "Ikke funnet: mangler gnr/bnr, adresse, postnummer og sted")
        return GeocodeResult(None, None, None, "Ikke funnet: " + "; ".join(tried))


# --- Google Maps and pasted coordinates (pure) ----------------------------------------------------


def address_query(c: Customer) -> str | None:
    """'Gardsvegen 1, 6887 Lærdal, Norge' from the address fields, or None when there are none."""
    town = " ".join(filter(None, (c.postcode, c.place)))
    parts = [p for p in (c.address, town) if p]
    return ", ".join(parts + ["Norge"]) if parts else None


def google_maps_url(c: Customer) -> str | None:
    """Google Maps at the customer's coordinates, else a search for the address (no API key)."""
    if c.has_coordinates:
        return f"https://www.google.com/maps/search/?api=1&query={c.lat:.6f},{c.lon:.6f}"
    query = address_query(c)
    return f"https://www.google.com/maps/search/?api=1&query={quote(query, safe='')}" if query else None


_DOT = r"-?\d{1,3}(?:\.\d+)?"
_LINK_PATTERNS = (
    re.compile(rf"!3d({_DOT})!4d({_DOT})"),  # exact place in a Google Maps link
    re.compile(rf"@({_DOT}),({_DOT})"),  # map centre
    re.compile(rf"[?&](?:q|query|ll|center)=({_DOT})\s*,\s*({_DOT})", re.IGNORECASE),
)
_NUM = r"[-+]?\d{1,3}(?:[.,]\d+)?"
_PAIR_SPACED = re.compile(rf"^\(?\s*({_NUM})\s*(?:;|,\s+|\s+)\s*({_NUM})\s*\)?$")
_PAIR_TIGHT = re.compile(r"^\(?\s*([-+]?\d{1,3}\.\d+),([-+]?\d{1,3}\.\d+)\s*\)?$")


def parse_number(text: str | None) -> float | None:
    """'59,66' or '59.66' -> 59.66; empty -> None; raises ValueError for other text."""
    raw = (text or "").strip().replace(" ", "")
    if not raw:
        return None
    return float(raw.replace(",", "."))


def parse_coordinates(text: str | None) -> tuple[float, float] | None:
    """(lat, lon) from a copied Google Maps pair ('59.66194, 10.79229') or a Google Maps link."""
    raw = unquote((text or "").strip())
    if not raw:
        return None
    for pattern in _LINK_PATTERNS:
        m = pattern.search(raw)
        if m:
            return _valid(float(m.group(1)), float(m.group(2)))
    for pattern in (_PAIR_SPACED, _PAIR_TIGHT):
        m = pattern.match(raw)
        if m:
            try:
                return _valid(parse_number(m.group(1)), parse_number(m.group(2)))
            except ValueError:
                return None
    return None


def _valid(lat: float | None, lon: float | None) -> tuple[float, float] | None:
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return lat, lon


def outside_norway(lat: float, lon: float) -> bool:
    return not (57.5 <= lat <= 71.5 and 4.0 <= lon <= 31.5)


def format_coordinates(lat: float, lon: float) -> str:
    """'59,661938° N, 10,792290° Ø'."""
    ns = "N" if lat >= 0 else "S"
    ew = "Ø" if lon >= 0 else "V"
    return f"{abs(lat):.6f}".replace(".", ",") + f"° {ns}, " + f"{abs(lon):.6f}".replace(".", ",") + f"° {ew}"
