from dataclasses import replace

from kundedb import db, repo
from kundedb.models import Customer


def test_insert_and_get(conn):
    c = repo.save_customer(conn, Customer(company="Testgård", postcode="430", gnr_bnr="12/3"))
    assert c.id is not None
    assert c.postcode == "0430"
    assert (c.gnr, c.bnr) == (12, 3)
    assert c.created and c.updated
    assert repo.get_customer(conn, c.id) == c
    assert repo.count_customers(conn) == 1


def test_unchanged_save_keeps_updated(conn):
    c = repo.save_customer(conn, Customer(company="A"), now="2026-01-01T00:00:00")
    again = repo.save_customer(conn, replace(c), now="2026-02-02T00:00:00")
    assert again.updated == "2026-01-01T00:00:00"
    changed = repo.save_customer(conn, replace(c, place="Ås"), now="2026-03-03T00:00:00")
    assert changed.updated == "2026-03-03T00:00:00"
    assert changed.created == "2026-01-01T00:00:00"


def _geocoded(conn, source="adresse"):
    c = repo.save_customer(conn, Customer(company="A", address="Vegen 1", postcode="1430"))
    assert repo.save_geocode(conn, c.id, c.address_key(), 59.6, 10.7, source, "test")
    return repo.get_customer(conn, c.id)


def test_address_change_clears_looked_up_coordinates(conn):
    c = _geocoded(conn)
    assert c.has_coordinates and c.geocode_source == "adresse"
    # a non-address change keeps them
    c = repo.save_customer(conn, replace(c, phone="91234567"))
    assert c.has_coordinates
    c = repo.save_customer(conn, replace(c, address="Vegen 2"))
    assert not c.has_coordinates
    assert c.geocode_source is None and c.geocode_date is None


def test_address_change_keeps_manual_coordinates(conn):
    c = repo.save_customer(conn, Customer(company="A", address="Vegen 1", lat=60.0, lon=10.0,
                                          geocode_source="manuell"))
    c = repo.save_customer(conn, replace(c, address="Vegen 2"))
    assert (c.lat, c.lon, c.geocode_source) == (60.0, 10.0, "manuell")


def test_address_and_coordinates_changed_together_keeps_new_coordinates(conn):
    c = _geocoded(conn)
    c = repo.save_customer(conn, replace(c, address="Vegen 2", lat=61.0, lon=11.0, geocode_source="manuell"))
    assert (c.lat, c.lon, c.geocode_source) == (61.0, 11.0, "manuell")


def test_save_geocode_skips_changed_address_and_manual(conn):
    c = repo.save_customer(conn, Customer(company="A", address="Vegen 1"))
    old_key = c.address_key()
    repo.save_customer(conn, replace(c, address="Vegen 9"))
    assert not repo.save_geocode(conn, c.id, old_key, 59.0, 10.0, "adresse", "x")
    m = repo.save_customer(conn, Customer(company="B", lat=60.0, lon=10.0, geocode_source="manuell"))
    assert not repo.save_geocode(conn, m.id, m.address_key(), 59.0, 10.0, "adresse", "x")
    assert not repo.save_geocode(conn, 9999, (), 59.0, 10.0, "adresse", "x")
    # asked for explicitly: replaces manual coordinates, but "not found" never erases coordinates
    assert not repo.save_geocode(conn, m.id, m.address_key(), None, None, None, "x", replace_manual=True)
    assert repo.save_geocode(conn, m.id, m.address_key(), 59.0, 10.0, "adresse", "x", replace_manual=True)
    m = repo.get_customer(conn, m.id)
    assert (m.lat, m.geocode_source) == (59.0, "adresse")
    assert not repo.save_geocode(conn, m.id, m.address_key(), None, None, None, "Ikke funnet")
    assert repo.get_customer(conn, m.id).lat == 59.0


def test_not_found_is_remembered(conn):
    c = repo.save_customer(conn, Customer(company="A", address="Vegen 1"))
    assert repo.save_geocode(conn, c.id, c.address_key(), None, None, "adresse", "Ikke funnet")
    c = repo.get_customer(conn, c.id)
    assert c.geocode_failed and c.geocode_source is None and c.geocode_note == "Ikke funnet"
    c = repo.save_customer(conn, replace(c, address="Vegen 2"))  # new address: try again
    assert not c.geocode_failed


def test_categories_and_delete(conn):
    a = repo.save_customer(conn, Customer(company="A", category="Frukt"))
    repo.save_customer(conn, Customer(company="B", category="bær"))
    repo.save_customer(conn, Customer(company="C", category=" Frukt "))
    repo.save_customer(conn, Customer(company="D"))
    assert repo.categories(conn) == ["bær", "Frukt"]
    assert repo.delete_customers(conn, [a.id]) == 1
    assert repo.get_customer(conn, a.id) is None


def test_backup(tmp_path):
    f = tmp_path / "k.db"
    c = db.connect(f)
    db.migrate(c)
    c.close()
    for _ in range(3):
        db.backup_database(f, tmp_path / "b", keep=2)
    assert len(list((tmp_path / "b").glob("*.db"))) == 2


def test_settings(conn):
    assert repo.get_settings(conn) == {"map_background": "kartverket", "google_maps_api_key": ""}
    repo.save_settings(conn, {"google_maps_api_key": "abc", "map_background": "osm"})
    assert repo.get_settings(conn)["google_maps_api_key"] == "abc"
    assert repo.get_settings(conn)["map_background"] == "osm"
