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


def login_admin(client):
    return client.post("/login", data={"email": "admin@frms.local", "password": "admin123"})


# =========================================================
# SECURITY TESTS
# =========================================================

def test_sec_logout_invalidates_session(client):
    # Login -> logout -> Dashboard must redirect to login
    login_admin(client)
    client.get("/logout")

    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers.get("Location", "")


def test_sec_sql_injection_attempt_on_login_should_fail(client):
    # SQL injection attempt -> invalid credentials
    payload_email = "' OR 1=1 --"
    r = client.post("/login", data={"email": payload_email, "password": "x"}, follow_redirects=True)

    assert r.status_code == 200
    assert b"Invalid credentials" in r.data


def test_sec_sql_injection_like_input_on_flights_search_should_not_crash(client):
    # Login needed to access /flights
    login_admin(client)

    # "weird" input -> system should not crash
    r = client.post("/flights", data={"flight_no": "IT' OR 1=1 --"}, follow_redirects=True)
    assert r.status_code == 200
    assert len(r.data) > 0


# =========================================================
# ACCEPTANCE (END-TO-END) TESTS
# =========================================================

def test_acc_customer_end_to_end_register_login_search_book_checkin(client):
    # 1) Register
    r1 = client.post("/register", data={"email": "acc@test.com", "password": "pw"}, follow_redirects=False)
    assert r1.status_code in (302, 303)

    # 2) Login
    r2 = client.post("/login", data={"email": "acc@test.com", "password": "pw"}, follow_redirects=False)
    assert r2.status_code in (302, 303)

    # 3) Flight search
    r3 = client.post("/flights", data={"flight_no": "IT"}, follow_redirects=True)
    assert r3.status_code == 200

    # 4) Booking -> Create PNR
    r4 = client.post(
        "/book/IT1234",
        data={
            "names[]": ["Acc Pax"],
            "ages[]": ["25"],
            "ssns[]": ["12345678901"],
            "seat_types[]": ["economy"],
        },
        follow_redirects=False
    )
    assert r4.status_code in (302, 303)
    loc = r4.headers.get("Location", "")
    assert "/booking/success/" in loc
    pnr = loc.split("/booking/success/")[-1]

    # 5) Check-in -> Should redirect to manage booking
    r5 = client.post("/checkin", data={"pnr": pnr}, follow_redirects=False)
    assert r5.status_code in (302, 303)
    assert f"/manage/{pnr}" in r5.headers.get("Location", "")


def test_acc_admin_end_to_end_generate_export_delete(client):
    # 1) Admin login
    login_admin(client)

    # 2) Roster generate
    r2 = client.get("/flight/IT1234/generate_roster", follow_redirects=False)
    assert r2.status_code in (302, 303)

    # 3) Export roster JSON
    r3 = client.get("/export/IT1234.json")
    assert r3.status_code == 200
    assert r3.is_json
    data = r3.get_json()
    assert "flight" in data and "passengers" in data

    # 4) Add a passenger to delete later
    con = db_conn()
    con.execute("""
        INSERT INTO passengers (flight_no, name, age, ssn, seat_type, seat_no, pnr)
        VALUES (?,?,?,?,?,?,?)
    """, ("IT1234", "ToDelete", 30, "99900011122", "economy", "10A", "PNRDEL"))
    pax_id = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    con.commit()
    con.close()

    # 5) Delete passenger (with admin access)
    r5 = client.post(f"/passenger/delete/{pax_id}", follow_redirects=False)
    assert r5.status_code in (302, 303)

    # 6) Is it deleted? (Acceptance inside verification)
    con = db_conn()
    row = con.execute("SELECT 1 FROM passengers WHERE id=?", (pax_id,)).fetchone()
    con.close()
    assert row is None
