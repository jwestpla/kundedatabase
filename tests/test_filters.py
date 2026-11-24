from kundedb.filters import (
    AND, CONTAINS, EMPTY, EQUALS, NOT_EMPTY, NOT_EQUALS, ONE_OF, OR, STARTS, Criterion, FilterSpec, load_filters,
    save_filters, search_matches,
)
from kundedb.models import Customer

A = Customer(id=1, company="Testgård AS", category="Frukt", postcode="1430", place="Ås", notes="Har tunnel")
B = Customer(id=2, full_name="Ola Nordmann", category="Bær", postcode="0150", lat=59.9, lon=10.7,
             geocode_source="adresse")


def hits(spec):
    return [c.id for c in (A, B) if spec.matches(c)]


def test_operators():
    assert hits(FilterSpec([Criterion("company", CONTAINS, "TESTGÅRD")])) == [1]
    assert hits(FilterSpec([Criterion("category", EQUALS, "frukt")])) == [1]
    assert hits(FilterSpec([Criterion("postcode", STARTS, "14")])) == [1]
    assert hits(FilterSpec([Criterion("category", NOT_EQUALS, "frukt")])) == [2]
    assert hits(FilterSpec([Criterion("company", EMPTY)])) == [2]
    assert hits(FilterSpec([Criterion("company", NOT_EMPTY)])) == [1]
    assert hits(FilterSpec([Criterion("postcode", ONE_OF, "0150, 9999")])) == [2]
    assert hits(FilterSpec([Criterion("coordinates", EMPTY)])) == [1]
    assert hits(FilterSpec([Criterion("geocode_source", EQUALS, "Adresse")])) == [2]


def test_combine_and_incomplete_rows():
    rows = [Criterion("category", EQUALS, "Frukt"), Criterion("postcode", EQUALS, "0150")]
    assert hits(FilterSpec(rows, AND)) == []
    assert hits(FilterSpec(rows, OR)) == [1, 2]
    # a row without value is ignored; no complete rows = no hits
    assert hits(FilterSpec([Criterion("category", EQUALS, "Frukt"), Criterion("place", CONTAINS, " ")])) == [1]
    assert hits(FilterSpec([Criterion("place", CONTAINS, "")])) == []
    assert FilterSpec([Criterion("place", ONE_OF, " , ")]).is_empty()


def test_search():
    assert search_matches(A, "")
    assert search_matches(A, "testgård tunnel")  # words in different fields, incl. notes
    assert not search_matches(A, "testgård ola")
    assert search_matches(B, "0150")


def test_save_and_load(tmp_path):
    path = tmp_path / "utvalg.json"
    assert load_filters(path) == {}
    spec = FilterSpec([Criterion("category", ONE_OF, "Frukt, Bær")], OR)
    save_filters(path, {"Frukt og bær": spec})
    assert load_filters(path) == {"Frukt og bær": spec}
    path.write_text("{ broken")
    assert load_filters(path) == {}
