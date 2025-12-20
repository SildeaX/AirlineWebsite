import os
import tempfile
import sqlite3
import pytest

import app as frms_app  # senin app.py

@pytest.fixture()
def client():
    # Temporary DB file 
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Redirect app to use temp DB
    frms_app.DATABASE = db_path
    frms_app.app.config["TESTING"] = True
    frms_app.app.config["SECRET_KEY"] = "test-secret"

    # DB init + seed
    with frms_app.app.app_context():
        frms_app.init_db()

    with frms_app.app.test_client() as client:
        yield client

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


def db_conn():
    # frms_app.DATABASE = connects to temp DB
    con = sqlite3.connect(frms_app.DATABASE)
    con.row_factory = sqlite3.Row
    return con


# ---------- AUTH WHITEBOX ----------

def test_login_user_not_found(client):
    r = client.post("/login", data={"email": "nouser@test.com", "password": "x"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Invalid credentials" in r.data  # flash mesajı

def test_login_wrong_password(client):
    # admin@frms.local with seed (pw admin123)
    r = client.post("/login", data={"email": "admin@frms.local", "password": "wrong"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Invalid credentials" in r.data

def test_login_success_redirect_dashboard(client):
    r = client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})
    # redirect after successful login
    assert r.status_code in (302, 303)
    assert "/dashboard" in r.headers.get("Location", "")


# ---------- ROLE WHITEBOX ----------

def login_as_viewer(client):
    # open viewer user
    client.post("/register", data={"email": "viewer@test.com", "password": "123"})
    # login
    client.post("/login", data={"email": "viewer@test.com", "password": "123"})

def test_admin_users_role_mismatch_redirect(client):
    login_as_viewer(client)
    r = client.get("/admin/users", follow_redirects=False)
    # login_required(role="admin") -> redirect to dashboard
    assert r.status_code in (302, 303)
    assert "/dashboard" in r.headers.get("Location", "")


# ---------- ROSTER WHITEBOX ----------

def test_export_roster_404_when_none(client):
    # login needed
    client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})
    r = client.get("/export/IT1234.json")
    # warning: no roster snapshot + no latest -> 404
    assert r.status_code == 404

def test_generate_roster_success_creates_row(client):
    client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})
    r = client.get("/flight/IT1234/generate_roster", follow_redirects=False)
    assert r.status_code in (302, 303)

    # Does roster row created?
    con = db_conn()
    c = con.execute("SELECT COUNT(*) AS c FROM rosters WHERE flight_no='IT1234'").fetchone()["c"]
    con.close()
    assert c >= 1


# ---------- DELETE PASSENGER WHITEBOX ----------

def test_delete_passenger_unauthorized_for_viewer(client):
    # viewer login
    login_as_viewer(client)

    # Add a passenger to DB (IT1234 flight)
    con = db_conn()
    con.execute("""
        INSERT INTO passengers (flight_no, name, age, ssn, seat_type, seat_no, pnr)
        VALUES (?,?,?,?,?,?,?)
    """, ("IT1234", "Temp Pax", 25, "12345678901", "economy", "10A", "PNR01"))
    pax_id = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    con.commit()
    con.close()

    r = client.post(f"/passenger/delete/{pax_id}", follow_redirects=False)
    # viewer -> unauthorized redirect dashboard
    assert r.status_code in (302, 303)
    assert "/dashboard" in r.headers.get("Location", "")

def test_delete_passenger_success_for_admin(client):
    client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})

    # add passenger
    con = db_conn()
    con.execute("""
        INSERT INTO passengers (flight_no, name, age, ssn, seat_type, seat_no, pnr)
        VALUES (?,?,?,?,?,?,?)
    """, ("IT1234", "Delete Me", 30, "99900011122", "economy", "11A", "PNR02"))
    pax_id = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    con.commit()
    con.close()

    r = client.post(f"/passenger/delete/{pax_id}", follow_redirects=False)
    assert r.status_code in (302, 303)

    # Is it deleted?
    con = db_conn()
    row = con.execute("SELECT 1 FROM passengers WHERE id=?", (pax_id,)).fetchone()
    con.close()
    assert row is None
def test_register_success_creates_user(client):
    r = client.post("/register", data={"email": "new@test.com", "password": "pw"}, follow_redirects=False)
    assert r.status_code in (302, 303)  # redirect to login

    con = db_conn()
    row = con.execute("SELECT role FROM users WHERE email=?", ("new@test.com",)).fetchone()
    con.close()
    assert row is not None
    assert row["role"] == "viewer"


def test_flight_search_post_returns_results(client):
    client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})
    r = client.post("/flights", data={"flight_no": "IT"}, follow_redirects=True)
    assert r.status_code == 200
    # Page html can change, but response should contain some data
    assert len(r.data) > 0


def test_booking_success_pnr_not_found(client):
    r = client.get("/booking/success/ZZZZZZ")
    assert r.status_code == 200
    assert b"PNR not found" in r.data


def test_view_latest_roster_fallback_when_no_snapshot(client):
    client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})

    # clear the rosters table -> no snapshot exists
    con = db_conn()
    con.execute("DELETE FROM rosters WHERE flight_no='IT1234'")
    con.commit()
    con.close()

    r = client.get("/flight/IT1234/roster")
    assert r.status_code == 200


def test_checkin_invalid_pnr_shows_error(client):
    r = client.post("/checkin", data={"pnr": "NOTREAL"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"PNR not found" in r.data


def test_export_roster_success_after_generate(client):
    client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})
    client.get("/flight/IT1234/generate_roster")

    r = client.get("/export/IT1234.json")
    assert r.status_code == 200
    assert r.is_json
    data = r.get_json()
    assert "flight" in data
    assert "passengers" in data
