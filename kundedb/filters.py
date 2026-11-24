"""Quick search and selection criteria ([felt] [operator] [verdi], combined with OG/ELLER). Pure.

Comparisons ignore case and extra spaces. Criteria that need a value but have none are ignored,
so a half-filled row doesn't change the result.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import FIELD_LABELS, GEOCODE_SOURCES, OTHER_LABELS, Customer

CONTAINS, EQUALS, STARTS, NOT_EQUALS, EMPTY, NOT_EMPTY, ONE_OF = (
    "inneholder", "er lik", "starter med", "er ikke", "er tom", "er ikke tom", "en av")
OPERATORS: tuple[str, ...] = (CONTAINS, EQUALS, STARTS, NOT_EQUALS, EMPTY, NOT_EMPTY, ONE_OF)
NO_VALUE: frozenset[str] = frozenset({EMPTY, NOT_EMPTY})
AND, OR = "OG", "ELLER"

# Fields offered in the filter builder: (key, label)
FILTER_FIELDS: tuple[tuple[str, str], ...] = (
    *FIELD_LABELS.items(),
    ("notes", OTHER_LABELS["notes"]),
    ("coordinates", OTHER_LABELS["coordinates"]),
    ("geocode_source", OTHER_LABELS["geocode_source"]),
)
FIELD_BY_LABEL = {label: key for key, label in FILTER_FIELDS}
LABEL_BY_FIELD = dict(FILTER_FIELDS)


def fold(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def field_text(c: Customer, key: str) -> str:
    """The value a criterion looks at, as text."""
    if key == "coordinates":
        return f"{c.lat:.6f}, {c.lon:.6f}" if c.has_coordinates else ""
    if key == "geocode_source":
        return GEOCODE_SOURCES.get(c.geocode_source or "", "")
    value = getattr(c, key, None)
    return "" if value is None else str(value)


@dataclass
class Criterion:
    field: str
    operator: str = CONTAINS
    value: str = ""

    @property
    def complete(self) -> bool:
        if self.field not in LABEL_BY_FIELD or self.operator not in OPERATORS:
            return False
        if self.operator in NO_VALUE:
            return True
        if self.operator == ONE_OF:
            return bool(_items(self.value))
        return bool(fold(self.value))

    def matches(self, c: Customer) -> bool:
        text = fold(field_text(c, self.field))
        value = fold(self.value)
        op = self.operator
        if op == CONTAINS:
            return value in text
        if op == EQUALS:
            return text == value
        if op == STARTS:
            return text.startswith(value)
        if op == NOT_EQUALS:
            return text != value
        if op == EMPTY:
            return not text
        if op == NOT_EMPTY:
            return bool(text)
        if op == ONE_OF:
            return text in _items(self.value)
        raise ValueError(op)


def _items(value: str) -> set[str]:
    return {fold(v) for v in (value or "").split(",") if fold(v)}


@dataclass
class FilterSpec:
    criteria: list[Criterion] = field(default_factory=list)
    combine: str = AND

    def active(self) -> list[Criterion]:
        return [c for c in self.criteria if c.complete]

    def is_empty(self) -> bool:
        return not self.active()

    def matches(self, c: Customer) -> bool:
        """True when the customer meets the criteria. No (complete) criteria: nothing matches."""
        active = self.active()
        if not active:
            return False
        test = all if self.combine == AND else any
        return test(crit.matches(c) for crit in active)

    def to_dict(self) -> dict:
        return {"combine": self.combine, "criteria": [asdict(c) for c in self.criteria]}

    @classmethod
    def from_dict(cls, data: dict) -> FilterSpec:
        criteria = [Criterion(str(c.get("field", "")), str(c.get("operator", CONTAINS)), str(c.get("value", "")))
                    for c in data.get("criteria", []) if isinstance(c, dict)]
        combine = data.get("combine") if data.get("combine") in (AND, OR) else AND
        return cls(criteria, combine)


def search_matches(c: Customer, query: str) -> bool:
    """Quick search: every word must appear somewhere in the customer's fields (incl. notes)."""
    words = fold(query).split()
    if not words:
        return True
    haystack = " ".join(fold(field_text(c, key)) for key, _ in FILTER_FIELDS)
    return all(w in haystack for w in words)


# --- Named filters (JSON in the data folder) ---------------------------------------------------


def load_filters(path: Path) -> dict[str, FilterSpec]:
    """Saved filters by name. A missing or unreadable file gives none."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    filters = data.get("filters", {}) if isinstance(data, dict) else {}
    return {str(name): FilterSpec.from_dict(spec) for name, spec in filters.items() if isinstance(spec, dict)}


def save_filters(path: Path, filters: dict[str, FilterSpec]) -> None:
    data = {"version": 1, "filters": {name: spec.to_dict() for name, spec in sorted(filters.items())}}
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
