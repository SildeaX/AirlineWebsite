import os
import tempfile
import sqlite3
import pytest

import app as frms_app


@pytest.fixture()
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    frms_app.DATABASE = db_path
    frms_app.app.config["TESTING"] = True
    frms_app.app.config["SECRET_KEY"] = "test-secret"

    with frms_app.app.app_context():
        frms_app.init_db()

    with frms_app.app.test_client() as client:
        yield client

    if os.path.exists(db_path):
        os.remove(db_path)


def db_conn():
    con = sqlite3.connect(frms_app.DATABASE)
    con.row_factory = sqlite3.Row
    return con


def login(client, email="admin@frms.local", password="admin123"):
    return client.post("/login", data={"email": email, "password": password})


# ----------------- AUTH BLACKBOX -----------------

def test_bb_guest_dashboard_redirects_to_login(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers.get("Location", "")

def test_bb_login_success_redirects_dashboard(client):
    r = login(client)
    assert r.status_code in (302, 303)
    assert "/dashboard" in r.headers.get("Location", "")

def test_bb_register_then_login_works(client):
    r = client.post("/register", data={"email": "x@test.com", "password": "pw"}, follow_redirects=False)
    assert r.status_code in (302, 303)  # redirect to login
    r2 = client.post("/login", data={"email": "x@test.com", "password": "pw"}, follow_redirects=False)
    assert r2.status_code in (302, 303)

def test_bb_logout_redirects_login(client):
    login(client)
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers.get("Location", "")


# ----------------- ADMIN AUTHZ BLACKBOX -----------------

def test_bb_admin_users_blocked_for_viewer(client):
    # viewer create + login
    client.post("/register", data={"email": "viewer@test.com", "password": "pw"})
    client.post("/login", data={"email": "viewer@test.com", "password": "pw"})

    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/dashboard" in r.headers.get("Location", "")


# ----------------- FLIGHTS & BOOKING BLACKBOX -----------------

def test_bb_flights_requires_login(client):
    r = client.get("/flights", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers.get("Location", "")

def test_bb_flight_search_returns_page(client):
    login(client)
    r = client.post("/flights", data={"flight_no": "IT"}, follow_redirects=True)
    assert r.status_code == 200
    assert len(r.data) > 0


# ----------------- CHECKIN BLACKBOX -----------------

def test_bb_checkin_invalid_pnr_shows_error(client):
    r = client.post("/checkin", data={"pnr": "NOTREAL"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"PNR not found" in r.data

def test_bb_checkin_valid_pnr_redirects_manage(client):
    # first, book a flight to get a PNR
    login(client)
    r = client.post(
        "/book/IT1234",
        data={
            "names[]": ["Test Pax"],
            "ages[]": ["30"],
            "ssns[]": ["12345678901"],
            "seat_types[]": ["economy"],
        },
        follow_redirects=False
    )
    assert r.status_code in (302, 303)
    loc = r.headers.get("Location", "")
    assert "/booking/success/" in loc
    pnr = loc.split("/booking/success/")[-1]

    # checkin
    r2 = client.post("/checkin", data={"pnr": pnr}, follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert f"/manage/{pnr}" in r2.headers.get("Location", "")


# ----------------- ROSTER EXPORT BLACKBOX -----------------

def test_bb_export_roster_404_without_roster(client):
    login(client)
    r = client.get("/export/IT1234.json")
    assert r.status_code == 404
    assert r.is_json
    assert r.get_json().get("error") == "No roster"

def test_bb_export_roster_success_after_generate(client):
    login(client)
    client.get("/flight/IT1234/generate_roster")
    r = client.get("/export/IT1234.json")
    assert r.status_code == 200
    assert r.is_json
    data = r.get_json()
    assert "flight" in data and "passengers" in data
