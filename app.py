
import sqlite3
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

from flask import (
    Flask, g, render_template, request,
    redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE = "frms.db"
NOSQL_FILE = os.path.join("data", "rosters_nosql.json")

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-in-production"  # required for sessions/cookies


# ---------- DB HELPERS ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables and insert sample data if empty."""
    db = get_db()

    # USERS (with roles)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer'  -- admin, operator, viewer
        )
    """)

    # FLIGHT INFO
    db.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_no TEXT UNIQUE NOT NULL,
            date_time TEXT NOT NULL,
            duration_minutes INTEGER,
            distance_km INTEGER,
            source TEXT,
            destination TEXT,
            vehicle_type TEXT,
            shared_flight_no TEXT,
            shared_company TEXT
        )
    """)

    # PILOTS
    db.execute("""
        CREATE TABLE IF NOT EXISTS pilots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            nationality TEXT,
            languages TEXT,
            vehicle_type TEXT,
            max_distance_km INTEGER,
            seniority TEXT  -- senior, junior, trainee
        )
    """)

    # CABIN CREW
    db.execute("""
        CREATE TABLE IF NOT EXISTS attendants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            nationality TEXT,
            languages TEXT,
            attendant_type TEXT,  -- chief, regular, chef
            vehicle_types TEXT
        )
    """)

    # PASSENGERS
    db.execute("""
        CREATE TABLE IF NOT EXISTS passengers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_no TEXT NOT NULL,
            name TEXT NOT NULL,
            age INTEGER,
            nationality TEXT,
            seat_type TEXT,  -- business or economy
            seat_no TEXT,    -- may be NULL
            group_id INTEGER,
            parent_id INTEGER
        )
    """)

    # ROSTERS (SQL store)
    db.execute("""
        CREATE TABLE IF NOT EXISTS rosters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_no TEXT NOT NULL,
            created_at TEXT NOT NULL,
            data_json TEXT NOT NULL
        )
    """)

    # LOGS (for admins, kept 6 months)
    db.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_email TEXT,
            level TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT
        )
    """)

    db.commit()

    # Seed minimal data if flights table empty
    cur = db.execute("SELECT COUNT(*) AS c FROM flights")
    if cur.fetchone()["c"] == 0:
        seed_data(db)

    # Ensure logs older than 6 months are pruned (NFR5)
    prune_old_logs(db)


def seed_data(db):
    flights = [
        ("IT1234", "2025-12-10 09:30", 120, 800,
         "Istanbul (IST)", "Berlin (BER)", "A320", None, None),
        ("IT2345", "2025-12-11 14:00", 180, 1500,
         "Istanbul (IST)", "London (LHR)", "B737", None, None),
        ("IT3456", "2025-12-12 20:15", 60, 400,
         "Ankara (ESB)", "Istanbul (IST)", "A321", "XY7890", "PartnerAir"),
    ]
    db.executemany("""
        INSERT INTO flights (
            flight_no, date_time, duration_minutes, distance_km,
            source, destination, vehicle_type,
            shared_flight_no, shared_company
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, flights)

    pilots = [
        ("John Senior", "Turkish", "TR,EN", "A320", 2000, "senior"),
        ("Jane Junior", "German", "DE,EN", "A320", 1500, "junior"),
        ("Alex Trainee", "Turkish", "TR,EN", "A320", 1000, "trainee"),
        ("Sam Senior", "British", "EN", "B737", 3000, "senior"),
        ("Lena Junior", "Turkish", "TR,EN", "B737", 2000, "junior"),
    ]
    db.executemany("""
        INSERT INTO pilots
        (name, nationality, languages, vehicle_type, max_distance_km, seniority)
        VALUES (?,?,?,?,?,?)
    """, pilots)

    attendants = [
        ("Ayşe Chief", "Turkish", "TR,EN", "chief", "A320,B737"),
        ("Mehmet Regular", "Turkish", "TR,EN", "regular", "A320"),
        ("Hans Regular", "German", "DE,EN", "regular", "A320,A321"),
        ("Julia Chef", "British", "EN", "chef", "B737,A321"),
    ]
    db.executemany("""
        INSERT INTO attendants
        (name, nationality, languages, attendant_type, vehicle_types)
        VALUES (?,?,?,?,?)
    """, attendants)

    passengers = [
        ("IT1234", "Ali Passenger", 30, "Turkish", "economy", None, 1, None),
        ("IT1234", "Veli Passenger", 28, "Turkish", "economy", None, 1, None),
        ("IT1234", "Ayse Passenger", 2, "Turkish", "economy", None, None, 1),
        ("IT1234", "John Business", 40, "British", "business", "1A", None, None),
        ("IT2345", "Passenger One", 25, "Turkish", "economy", None, None, None),
        ("IT2345", "Passenger Two", 27, "German", "economy", None, None, None),
    ]
    db.executemany("""
        INSERT INTO passengers
        (flight_no, name, age, nationality, seat_type, seat_no, group_id, parent_id)
        VALUES (?,?,?,?,?,?,?,?)
    """, passengers)

    # create default admin for convenience
    pw_hash = generate_password_hash("admin123", method="pbkdf2:sha256")
    db.execute("""
        INSERT OR IGNORE INTO users (email, password_hash, role)
        VALUES (?,?,?)
    """, ("admin@frms.local", pw_hash, "admin"))

    db.commit()


def prune_old_logs(db):
    cutoff = datetime.utcnow() - timedelta(days=180)
    db.execute(
        "DELETE FROM logs WHERE timestamp < ?",
        (cutoff.isoformat(),)
    )
    db.commit()


def log_action(level, action, details=""):
    db = get_db()
    user = current_user()
    email = user["email"] if user else None
    db.execute("""
        INSERT INTO logs (timestamp, user_email, level, action, details)
        VALUES (?,?,?,?,?)
    """, (datetime.utcnow().isoformat(), email, level, action, details))
    db.commit()


# ---------- AUTH & ROLE HELPERS ----------

def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    cur = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],))
    return cur.fetchone()


def login_required(role=None):
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in first.", "warning")
                return redirect(url_for("login", next=request.path))
            if role and user["role"] != role:
                flash("You are not authorized to view this page.", "danger")
                return redirect(url_for("dashboard"))
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ---------- ROUTES: AUTH ----------

@app.route("/", methods=["GET"])
def home():
    user = current_user()
    if user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        if not email or not password:
            flash("Email and password required.", "danger")
            return redirect(url_for("register"))

        pw_hash = generate_password_hash(password, method="pbkdf2:sha256")

        try:
            db.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?,?,?)",
                (email, pw_hash, "viewer"),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Email already registered.", "danger")
            return redirect(url_for("register"))

        log_action("INFO", "User registered", f"{email}")
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", user=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        cur = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            log_action("INFO", "Login", email)
            next_page = request.args.get("next") or url_for("dashboard")
            return redirect(next_page)
        else:
            log_action("WARN", "LoginFailed", email)
            flash("Invalid credentials.", "danger")
            return redirect(url_for("login"))
    return render_template("login.html", user=current_user())


@app.route("/logout")
def logout():
    user = current_user()
    if user:
        log_action("INFO", "Logout", user["email"])
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# ---------- DASHBOARDS BY ROLE ----------

@app.route("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    db = get_db()
    cur = db.execute("""
        SELECT * FROM flights
        ORDER BY date_time ASC
        LIMIT 10
    """)
    flights = cur.fetchall()

    if user["role"] == "admin":
        # quick stats for admin
        user_count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        roster_count = db.execute("SELECT COUNT(*) AS c FROM rosters").fetchone()["c"]
        return render_template(
            "dashboard_admin.html",
            user=user, flights=flights,
            user_count=user_count, roster_count=roster_count
        )
    elif user["role"] == "operator":
        return render_template("dashboard_operator.html", user=user, flights=flights)
    else:
        return render_template("dashboard_viewer.html", user=user, flights=flights)


# ---------- USER MANAGEMENT (ADMIN) ----------

@app.route("/admin/users", methods=["GET", "POST"])
@login_required(role="admin")
def manage_users():
    db = get_db()
    if request.method == "POST":
        user_id = request.form["user_id"]
        new_role = request.form["role"]
        db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        db.commit()
        log_action("INFO", "ChangeRole", f"user_id={user_id} -> {new_role}")
        flash("Role updated.", "success")

    cur = db.execute("SELECT id, email, role FROM users ORDER BY email")
    users = cur.fetchall()
    return render_template("manage_users.html", user=current_user(), users=users)


# ---------- LOG VIEW (ADMIN) ----------

@app.route("/admin/logs")
@login_required(role="admin")
def view_logs():
    db = get_db()
    level = request.args.get("level")
    query = "SELECT * FROM logs ORDER BY timestamp DESC LIMIT 200"
    params = []
    if level:
        query = "SELECT * FROM logs WHERE level = ? ORDER BY timestamp DESC LIMIT 200"
        params.append(level)
    logs = db.execute(query, params).fetchall()
    return render_template("logs.html", user=current_user(), logs=logs, level=level)


# ---------- FLIGHT SEARCH ----------

@app.route("/flights", methods=["GET", "POST"])
@login_required()
def flight_search():
    user = current_user()
    flights = []
    if request.method == "POST":
        db = get_db()
        flight_no = request.form.get("flight_no", "").strip().upper()
        date_str = request.form.get("date", "").strip()
        source = request.form.get("source", "").strip()
        dest = request.form.get("destination", "").strip()

        query = "SELECT * FROM flights WHERE 1=1"
        params = []

        if flight_no:
            query += " AND flight_no LIKE ?"
            params.append(f"%{flight_no}%")
        if date_str:
            query += " AND date_time LIKE ?"
            params.append(f"{date_str}%")
        if source:
            query += " AND source LIKE ?"
            params.append(f"%{source}%")
        if dest:
            query += " AND destination LIKE ?"
            params.append(f"%{dest}%")

        cur = db.execute(query, params)
        flights = cur.fetchall()
        log_action("INFO", "FlightSearch", f"{flight_no} {date_str}")

    return render_template("flight_search.html", user=user, flights=flights)


# ---------- SEAT MAP & ROSTER GENERATION ----------

def build_seat_map(vehicle_type):
    cfg = {
        "A320": (20, 3),
        "B737": (22, 4),
        "A321": (24, 5),
    }
    rows, business_rows = cfg.get(vehicle_type, (20, 3))
    seats = []
    for r in range(1, rows + 1):
        for col in "ABCDEF":
            seat_no = f"{r}{col}"
            seat_type = "business" if r <= business_rows else "economy"
            seats.append({"seat_no": seat_no, "seat_type": seat_type})
    return seats


def assign_seats(vehicle_type, passengers):
    seat_map = build_seat_map(vehicle_type)
    used = {p["seat_no"] for p in passengers if p["seat_no"]}
    free = [s for s in seat_map if s["seat_no"] not in used]

    for p in passengers:
        if p["seat_no"]:
            continue
        if p["age"] is not None and p["age"] <= 2:
            continue  # infants no seat
        for s in free:
            if s["seat_type"] == p["seat_type"]:
                p["seat_no"] = s["seat_no"]
                used.add(s["seat_no"])
                free.remove(s)
                break
    return passengers


@app.route("/flight/<flight_no>/roster")
@login_required()
def flight_roster(flight_no):
    db = get_db()

    flight = db.execute(
        "SELECT * FROM flights WHERE flight_no = ?", (flight_no,)
    ).fetchone()
    if not flight:
        log_action("ERROR", "FlightNotFound", flight_no)
        return render_template("error.html", user=current_user(),
                               message="Flight not found")

    # crew
    all_pilots = db.execute("""
        SELECT * FROM pilots
        WHERE vehicle_type = ? AND max_distance_km >= ?
    """, (flight["vehicle_type"], flight["distance_km"])).fetchall()

    seniors = [p for p in all_pilots if p["seniority"] == "senior"]
    juniors = [p for p in all_pilots if p["seniority"] == "junior"]
    trainees = [p for p in all_pilots if p["seniority"] == "trainee"]

    crew_pilots = []
    if seniors:
        crew_pilots.append(seniors[0])
    if juniors:
        crew_pilots.append(juniors[0])
    if trainees:
        crew_pilots.append(trainees[0])

    att_all = db.execute("SELECT * FROM attendants").fetchall()
    cabin = [a for a in att_all if flight["vehicle_type"] in (a["vehicle_types"] or "")]
    cabin = cabin[:6]

    # passengers
    pass_rows = db.execute("""
        SELECT * FROM passengers WHERE flight_no = ?
    """, (flight_no,)).fetchall()
    passengers = [dict(p) for p in pass_rows]

    passengers = assign_seats(flight["vehicle_type"], passengers)

    # seat map for plane view
    seat_map = build_seat_map(flight["vehicle_type"])
    seat_lookup = {p["seat_no"]: p for p in passengers if p["seat_no"]}
    for seat in seat_map:
        seat["occupant"] = seat_lookup.get(seat["seat_no"])
    seat_rows_dict = defaultdict(list)
    for seat in seat_map:
        row_num = int(''.join(ch for ch in seat["seat_no"] if ch.isdigit()))
        seat_rows_dict[row_num].append(seat)
    seat_rows = {
        row: sorted(seat_rows_dict[row], key=lambda s: s["seat_no"])
        for row in sorted(seat_rows_dict.keys())
    }

    # roster object
    roster = {
        "flight": dict(flight),
        "pilots": [dict(p) for p in crew_pilots],
        "cabin": [dict(c) for c in cabin],
        "passengers": passengers,
    }

    # save automatically to SQL
    db.execute("""
        INSERT INTO rosters (flight_no, created_at, data_json)
        VALUES (?, ?, ?)
    """, (flight_no, datetime.utcnow().isoformat(), json.dumps(roster)))
    db.commit()

    log_action("INFO", "GenerateRoster", flight_no)

    return render_template(
        "roster.html",
        user=current_user(),
        flight=flight,
        pilots=crew_pilots,
        cabin=cabin,
        passengers=passengers,
        seat_rows=seat_rows,
    )


# ---------- MANUAL SEAT UPDATE (operator/admin) ----------

@app.route("/flight/<flight_no>/update_seat", methods=["POST"])
@login_required()
def update_seat(flight_no):
    user = current_user()
    if user["role"] not in ("operator", "admin"):
        flash("Only operators or admins can change seats.", "danger")
        return redirect(url_for("flight_roster", flight_no=flight_no))

    passenger_id = request.form["passenger_id"]
    new_seat = request.form["seat_no"].strip().upper()

    db = get_db()
    db.execute(
        "UPDATE passengers SET seat_no = ? WHERE id = ? AND flight_no = ?",
        (new_seat, passenger_id, flight_no),
    )
    db.commit()
    log_action("INFO", "ManualSeatChange",
               f"flight={flight_no}, passenger_id={passenger_id}, seat={new_seat}")
    flash("Seat updated.", "success")
    return redirect(url_for("flight_roster", flight_no=flight_no))


# ---------- SAVE ROSTER TO NoSQL JSON ----------

@app.route("/flight/<flight_no>/save_nosql")
@login_required()
def save_roster_nosql(flight_no):
    db = get_db()
    row = db.execute("""
        SELECT data_json FROM rosters
        WHERE flight_no = ?
        ORDER BY created_at DESC LIMIT 1
    """, (flight_no,)).fetchone()
    if not row:
        flash("No roster found to save.", "warning")
        return redirect(url_for("flight_roster", flight_no=flight_no))

    roster = json.loads(row["data_json"])

    os.makedirs(os.path.dirname(NOSQL_FILE), exist_ok=True)
    if os.path.exists(NOSQL_FILE):
        with open(NOSQL_FILE, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    else:
        all_data = {}

    all_data[flight_no] = roster
    with open(NOSQL_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2)

    log_action("INFO", "SaveRosterNoSQL", flight_no)
    flash("Roster saved to NoSQL JSON file.", "success")
    return redirect(url_for("flight_roster", flight_no=flight_no))


# ---------- EXPORT JSON ----------

@app.route("/export/<flight_no>.json")
@login_required()
def export_roster(flight_no):
    db = get_db()
    row = db.execute("""
        SELECT data_json FROM rosters
        WHERE flight_no = ?
        ORDER BY created_at DESC LIMIT 1
    """, (flight_no,)).fetchone()
    if not row:
        return jsonify({"error": "No roster found for this flight"}), 404
    data = json.loads(row["data_json"])
    log_action("INFO", "ExportRoster", flight_no)
    return jsonify(data)


# ---------- API ENDPOINTS (simulate external APIs) ----------

@app.route("/api/flights")
def api_flights():
    db = get_db()
    flight_no = request.args.get("flight_no", "").strip().upper()
    query = "SELECT * FROM flights WHERE 1=1"
    params = []
    if flight_no:
        query += " AND flight_no LIKE ?"
        params.append(f"%{flight_no}%")
    flights = [dict(row) for row in db.execute(query, params)]
    return jsonify(flights)


@app.route("/api/flight/<flight_no>")
def api_flight_detail(flight_no):
    db = get_db()
    flight = db.execute(
        "SELECT * FROM flights WHERE flight_no = ?", (flight_no,)
    ).fetchone()
    if not flight:
        return jsonify({"error": "Flight not found"}), 404
    return jsonify(dict(flight))


@app.route("/api/crew")
def api_crew():
    db = get_db()
    pilots = [dict(p) for p in db.execute("SELECT * FROM pilots")]
    return jsonify(pilots)


@app.route("/api/cabin")
def api_cabin():
    db = get_db()
    attendants = [dict(a) for a in db.execute("SELECT * FROM attendants")]
    return jsonify(attendants)


@app.route("/api/passengers")
def api_passengers():
    db = get_db()
    flight_no = request.args.get("flight_no")
    if not flight_no:
        return jsonify({"error": "flight_no parameter required"}), 400
    passengers = [dict(p) for p in db.execute(
        "SELECT * FROM passengers WHERE flight_no = ?",
        (flight_no,)
    )]
    return jsonify(passengers)


# ---------- ERROR HANDLER ----------

@app.errorhandler(500)
def internal_error(e):
    log_action("ERROR", "InternalServerError", str(e))
    return render_template("error.html", user=current_user(),
                           message="Internal server error"), 500


# ---------- MAIN ----------

if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        with app.app_context():
            init_db()
    else:
        with app.app_context():
            init_db()

    app.run(debug=True, host="0.0.0.0", port=5001)


