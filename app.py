import sqlite3
import json
import os
import random
import string
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from flask import (
    Flask, g, render_template, request,
    redirect, url_for, session, flash, jsonify, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash

# Configuration
DATABASE = "frms.db"
NOSQL_FILE = os.path.join("data", "rosters_nosql.json")

app = Flask(__name__)
# Secret key is required for session management
app.config["SECRET_KEY"] = "change-this-in-production"

# ---------- DB HELPERS ----------

def get_db():
    """Connect to the SQLite database."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    """Close the database connection at end of request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()

def utc_now_iso():
    """Get current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()

def init_db():
    """Initialize database tables and seed data if empty."""
    db = get_db()

    # Users Table
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer'
        )
    """)

    # Flights Table
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

    # Pilots Table
    db.execute("""
        CREATE TABLE IF NOT EXISTS pilots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            nationality TEXT,
            languages TEXT,
            vehicle_type TEXT,
            max_distance_km INTEGER,
            seniority TEXT
        )
    """)

    # Attendants Table
    db.execute("""
        CREATE TABLE IF NOT EXISTS attendants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            nationality TEXT,
            languages TEXT,
            attendant_type TEXT,
            vehicle_types TEXT
        )
    """)

    # Passengers Table (With SSN and PNR)
    db.execute("""
        CREATE TABLE IF NOT EXISTS passengers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_no TEXT NOT NULL,
            name TEXT NOT NULL,
            age INTEGER,
            ssn TEXT, 
            seat_type TEXT,
            seat_no TEXT,
            group_id INTEGER,
            parent_id INTEGER,
            pnr TEXT
        )
    """)

    # Rosters Table (JSON Storage)
    db.execute("""
        CREATE TABLE IF NOT EXISTS rosters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flight_no TEXT NOT NULL,
            created_at TEXT NOT NULL,
            data_json TEXT NOT NULL
        )
    """)

    # Logs Table
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

    # Seed data if flights are empty
    cur = db.execute("SELECT COUNT(*) AS c FROM flights")
    if cur.fetchone()["c"] == 0:
        seed_data(db)

    prune_old_logs(db)

def seed_data(db):
    """Insert sample data."""
    flights = [
        ("IT1234", "2025-12-10 09:30", 120, 800, "Istanbul (IST)", "Berlin (BER)", "A320", None, None),
        ("IT2345", "2025-12-11 14:00", 180, 1500, "Istanbul (IST)", "London (LHR)", "B737", None, None),
        ("IT3456", "2025-12-12 20:15", 60, 400, "Ankara (ESB)", "Istanbul (IST)", "A321", "XY7890", "PartnerAir"),
        ("IT7777", "2025-12-13 10:00", 240, 3200, "Istanbul (IST)", "Dubai (DXB)", "A330", None, None),
    ]
    db.executemany("""
        INSERT INTO flights (flight_no, date_time, duration_minutes, distance_km, source, destination, vehicle_type, shared_flight_no, shared_company) 
        VALUES (?,?,?,?,?,?,?,?,?)
    """, flights)

    # Pilots
    pilots = [
        ("John Senior", "Turkish", "TR,EN", "A320", 2000, "senior"),
        ("Jane Junior", "German", "DE,EN", "A320", 1500, "junior"),
        ("Alex Trainee", "Turkish", "TR,EN", "A320", 1000, "trainee"),
        ("Sam Senior", "British", "EN", "B737", 3000, "senior"),
        ("Lena Junior", "Turkish", "TR,EN", "B737", 2000, "junior"),
        ("Trainee B", "Turkish", "TR,EN", "B737", 1500, "trainee"),
        ("Captain A321", "Turkish", "TR,EN", "A321", 2500, "senior"),
        ("FO A321", "German", "DE,EN", "A321", 2200, "junior"),
        ("Captain A330", "Turkish", "TR,EN", "A330", 9000, "senior"),
        ("FO A330", "German", "DE,EN", "A330", 8000, "junior"),
        ("Trainee A330", "Turkish", "TR,EN", "A330", 5000, "trainee"),
    ]
    db.executemany("INSERT INTO pilots (name, nationality, languages, vehicle_type, max_distance_km, seniority) VALUES (?,?,?,?,?,?)", pilots)

    # Attendants
    attendants = [
        ("Ayşe Chief", "Turkish", "TR,EN", "chief", "A320,B737"),
        ("Mehmet Regular", "Turkish", "TR,EN", "regular", "A320"),
        ("Hans Regular", "German", "DE,EN", "regular", "A320,A321"),
        ("Julia Chef", "British", "EN", "chef", "B737,A321"),
        ("Lead A330", "Turkish", "TR,EN", "chief", "A330"),
        ("Crew A330-1", "Turkish", "TR,EN", "regular", "A330"),
        ("Crew A330-2", "German", "DE,EN", "regular", "A330"),
        ("Crew A330-3", "Turkish", "TR,EN", "regular", "A330"),
        ("Chef A330", "British", "EN", "chef", "A330"),
        ("Crew A330-4", "German", "DE,EN", "regular", "A330"),
    ]
    db.executemany("INSERT INTO attendants (name, nationality, languages, attendant_type, vehicle_types) VALUES (?,?,?,?,?)", attendants)

    # Passengers (SSN based)
    passengers = [
        ("IT1234", "Ali Passenger", 30, "11111111111", "economy", None, 1, None),
        ("IT1234", "Veli Passenger", 28, "22222222222", "economy", None, 1, None),
        ("IT1234", "Ayse Infant", 2, "33333333333", "economy", None, None, 1),
        ("IT1234", "John Business", 40, "44444444444", "business", "1A", None, None),
        ("IT2345", "Passenger One", 25, "55555555555", "economy", None, None, None),
        ("IT2345", "Passenger Two", 27, "66666666666", "economy", None, None, None),
        ("IT7777", "A330 Pax 1", 33, "77777777777", "economy", None, None, None),
        ("IT7777", "A330 Pax 2", 29, "88888888888", "economy", None, None, None),
        ("IT7777", "A330 Biz 1", 45, "99999999999", "business", None, None, None),
    ]
    db.executemany("""
        INSERT INTO passengers (flight_no, name, age, ssn, seat_type, seat_no, group_id, parent_id)
        VALUES (?,?,?,?,?,?,?,?)
    """, passengers)

    # Admin User
    pw_hash = generate_password_hash("admin123", method="pbkdf2:sha256")
    db.execute("INSERT OR IGNORE INTO users (email, password_hash, role) VALUES (?,?,?)", ("admin@frms.local", pw_hash, "admin"))

    db.commit()

def prune_old_logs(db):
    """Delete logs older than 6 months."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    db.execute("DELETE FROM logs WHERE timestamp < ?", (cutoff.isoformat(),))
    db.commit()

def log_action(level, action, details=""):
    """Log system events."""
    db = get_db()
    user = current_user()
    email = user["email"] if user else "guest"
    try:
        db.execute("INSERT INTO logs (timestamp, user_email, level, action, details) VALUES (?,?,?,?,?)", 
                   (utc_now_iso(), email, level, action, details))
        db.commit()
    except:
        pass

def generate_pnr():
    """Generate 6-char random alphanumeric PNR."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def check_and_update_schema():
    """Ensure schema updates (like SSN column) are applied."""
    db = get_db()
    try:
        db.execute("SELECT ssn FROM passengers LIMIT 1")
    except sqlite3.OperationalError:
        try:
            db.execute("ALTER TABLE passengers ADD COLUMN ssn TEXT")
            db.commit()
        except:
            pass

# ---------- SEAT MAP HELPERS ----------

PLANE_LAYOUTS = {
    "A320": {"rows": 20, "biz": 3, "cols": "ABCDEF"},
    "B737": {"rows": 22, "biz": 4, "cols": "ABCDEF"},
    "A321": {"rows": 24, "biz": 5, "cols": "ABCDEF"},
    "A330": {"rows": 30, "biz": 6, "cols": "ABCDEFGH"},
}

def build_seat_map(vtype):
    """Generate list of all seats for a plane type."""
    c = PLANE_LAYOUTS.get(vtype)
    seats = []
    if not c: return []
    for r in range(1, c["rows"] + 1):
        for col in c["cols"]:
            seats.append({"seat_no": f"{r}{col}", "seat_type": "business" if r <= c["biz"] else "economy"})
    return seats

def build_seat_rows(vehicle_type, passengers):
    """Organize passengers into rows for visual display."""
    seat_map = build_seat_map(vehicle_type)
    seat_lookup = {p["seat_no"]: p for p in passengers if p["seat_no"]}
    
    seat_rows_dict = defaultdict(list)
    for seat in seat_map:
        seat["occupant"] = seat_lookup.get(seat["seat_no"])
        row_num = int(''.join(ch for ch in seat["seat_no"] if ch.isdigit()))
        seat_rows_dict[row_num].append(seat)

    return {r: sorted(seat_rows_dict[r], key=lambda s: s["seat_no"]) for r in sorted(seat_rows_dict.keys())}

# ---------- AUTH & ROLES ----------

def current_user():
    """Get current logged-in user."""
    if "user_id" not in session: return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

def login_required(role=None):
    """Decorator for route protection."""
    from functools import wraps
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in first.", "warning")
                return redirect(url_for("login", next=request.path))
            if role and user["role"] != role:
                flash("Unauthorized.", "danger")
                return redirect(url_for("dashboard"))
            return func(*args, **kwargs)
        return wrapper
    return decorator

# ---------- ROUTES: AUTH ----------

@app.route("/", methods=["GET"])
def home():
    if current_user(): return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    response = make_response(render_template("login.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db = get_db()
        try:
            db.execute("INSERT INTO users (email, password_hash, role) VALUES (?,?,?)", 
                       (email, generate_password_hash(password, method="pbkdf2:sha256"), "viewer"))
            db.commit()
            flash("Registered. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email exists.", "danger")
    return render_template("register.html", user=current_user())

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# ---------- DASHBOARDS ----------

@app.route("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    db = get_db()
    flights = db.execute("SELECT * FROM flights ORDER BY date_time ASC LIMIT 10").fetchall()
    
    if user["role"] == "admin":
        uc = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        rc = db.execute("SELECT COUNT(*) as c FROM rosters").fetchone()["c"]
        return render_template("dashboard_admin.html", user=user, flights=flights, user_count=uc, roster_count=rc)
    elif user["role"] == "operator":
        return render_template("dashboard_operator.html", user=user, flights=flights)
    return render_template("dashboard_viewer.html", user=user, flights=flights)

# ---------- ADMIN FUNCTIONS (RESTORED) ----------

@app.route("/admin/users", methods=["GET", "POST"])
@login_required(role="admin")
def manage_users():
    """Admin: Change user roles."""
    db = get_db()
    if request.method == "POST":
        uid, role = request.form["user_id"], request.form["role"]
        target = db.execute("SELECT role FROM users WHERE id=?",(uid,)).fetchone()
        if target and target["role"] != "admin":
            db.execute("UPDATE users SET role=? WHERE id=?",(role,uid))
            db.commit()
            flash("Role updated.", "success")
        else:
            flash("Cannot change admin role.", "danger")
    users = db.execute("SELECT id, email, role FROM users ORDER BY email").fetchall()
    return render_template("manage_users.html", user=current_user(), users=users)

@app.route("/admin/logs")
@login_required(role="admin")
def view_logs():
    """Admin: View system logs."""
    db = get_db()
    level = request.args.get("level")
    sql = "SELECT * FROM logs WHERE level=? ORDER BY timestamp DESC LIMIT 200" if level else "SELECT * FROM logs ORDER BY timestamp DESC LIMIT 200"
    logs = db.execute(sql, (level,) if level else ()).fetchall()
    return render_template("logs.html", user=current_user(), logs=logs, level=level)

# ---------- FLIGHTS & BOOKING ----------

@app.route("/flights", methods=["GET", "POST"])
@login_required()
def flight_search():
    flights = []
    if request.method == "POST":
        db = get_db()
        fno = request.form.get("flight_no","").strip().upper()
        flights = db.execute("SELECT * FROM flights WHERE flight_no LIKE ?", (f"%{fno}%",)).fetchall()
    return render_template("flight_search.html", user=current_user(), flights=flights)

@app.route("/book/<flight_no>", methods=["GET", "POST"])
@login_required()
def book_flight(flight_no):
    check_and_update_schema()
    db = get_db()
    flight = db.execute("SELECT * FROM flights WHERE flight_no = ?", (flight_no,)).fetchone()
    
    if request.method == "POST":
        names = request.form.getlist("names[]")
        ages = request.form.getlist("ages[]")
        ssns = request.form.getlist("ssns[]")
        seat_types = request.form.getlist("seat_types[]")
        
        pnr = generate_pnr()
        while db.execute("SELECT 1 FROM passengers WHERE pnr=?", (pnr,)).fetchone():
            pnr = generate_pnr()

        for i in range(len(names)):
            db.execute("""
                INSERT INTO passengers (flight_no, name, age, ssn, seat_type, pnr)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (flight_no, names[i], ages[i], ssns[i], seat_types[i], pnr))
        
        db.commit()
        return redirect(url_for("booking_success", pnr=pnr))

    return render_template("booking.html", user=current_user(), flight=flight)

@app.route("/booking/success/<pnr>")
def booking_success(pnr):
    db = get_db()
    passengers = db.execute("SELECT * FROM passengers WHERE pnr=?", (pnr,)).fetchall()
    if not passengers: return "PNR not found"
    # Convert sqlite3.Row objects to dictionaries for template compatibility
    passengers = [dict(p) for p in passengers]
    flight = db.execute("SELECT * FROM flights WHERE flight_no=?", (passengers[0]["flight_no"],)).fetchone()
    return render_template("booking_success.html", user=current_user(), pnr=pnr, flight=flight, passengers=passengers)

# ---------- CHECK-IN & SEAT MANAGEMENT ----------

@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    """Passenger check-in via PNR."""
    if request.method == "POST":
        pnr = request.form.get("pnr", "").strip().upper()
        db = get_db()
        
        passengers = db.execute("SELECT * FROM passengers WHERE pnr = ?", (pnr,)).fetchall()
        if not passengers:
            flash("PNR not found.", "danger")
            return redirect(url_for("checkin"))
        
        flight_no = passengers[0]["flight_no"]
        flight = db.execute("SELECT * FROM flights WHERE flight_no = ?", (flight_no,)).fetchone()
        
        # Auto-assign random seats if missing
        perform_random_assignment(db, flight, passengers)
        
        return redirect(url_for("manage_booking", pnr=pnr))
        
    return render_template("checkin.html", user=current_user())

def perform_random_assignment(db, flight, pnr_passengers):
    """Logic to assign random seats to checked-in passengers."""
    vehicle_type = flight["vehicle_type"]
    all_seats = build_seat_map(vehicle_type)
    
    all_flight_pax = db.execute("SELECT seat_no FROM passengers WHERE flight_no = ?", (flight["flight_no"],)).fetchall()
    occupied_seats = set(p["seat_no"] for p in all_flight_pax if p["seat_no"])
    
    free_business = [s["seat_no"] for s in all_seats if s["seat_type"] == "business" and s["seat_no"] not in occupied_seats]
    free_economy = [s["seat_no"] for s in all_seats if s["seat_type"] == "economy" and s["seat_no"] not in occupied_seats]
    
    random.shuffle(free_business)
    random.shuffle(free_economy)
    
    updates_made = False
    
    for p in pnr_passengers:
        if p["seat_no"]: continue
        if p["age"] and int(p["age"]) <= 2: continue # Infants skip
            
        needed_class = p["seat_type"]
        assigned_seat = None
        
        if needed_class == "business":
            if free_business: assigned_seat = free_business.pop()
        else:
            if free_economy: assigned_seat = free_economy.pop()
        
        if assigned_seat:
            db.execute("UPDATE passengers SET seat_no = ? WHERE id = ?", (assigned_seat, p["id"]))
            occupied_seats.add(assigned_seat)
            updates_made = True
            
    if updates_made: db.commit()

@app.route("/manage/<pnr>", methods=["GET", "POST"])
def manage_booking(pnr):
    """Page to change seats for a PNR."""
    db = get_db()
    
    # Fetch passengers associated with the PNR
    passengers = db.execute("SELECT * FROM passengers WHERE pnr = ?", (pnr,)).fetchall()
    
    if not passengers:
        return redirect(url_for("checkin"))
    
    # Convert sqlite3.Row objects to dictionaries for template compatibility
    passengers = [dict(p) for p in passengers]
    
    # Get flight details
    flight = db.execute("SELECT * FROM flights WHERE flight_no = ?", (passengers[0]["flight_no"],)).fetchone()
    
    # Handle seat change request (POST)
    if request.method == "POST":
        passenger_id = int(request.form.get("passenger_id"))
        new_seat = request.form.get("new_seat", "").strip().upper()
        
        # Find the specific passenger in the PNR group
        target_pax = next((p for p in passengers if p["id"] == passenger_id), None)
        
        if target_pax:
            # Validate the new seat against the seat map
            seat_map = build_seat_map(flight["vehicle_type"])
            target_seat_info = next((s for s in seat_map if s["seat_no"] == new_seat), None)
            
            # Check if the seat is already occupied
            occupant = db.execute("SELECT * FROM passengers WHERE flight_no = ? AND seat_no = ?", 
                                  (flight["flight_no"], new_seat)).fetchone()
            
            if not target_seat_info:
                flash("Invalid seat.", "danger")
            elif target_seat_info["seat_type"] != target_pax["seat_type"]:
                flash("Wrong class (Cannot move between Economy/Business).", "danger")
            elif occupant:
                flash("Seat occupied.", "danger")
            else:
                # Update the seat in the database
                db.execute("UPDATE passengers SET seat_no = ? WHERE id = ?", (new_seat, passenger_id))
                db.commit()
                flash("Seat changed.", "success")
                return redirect(url_for("manage_booking", pnr=pnr))

    # PREPARE DATA FOR VISUAL SEAT MAP
    # 1. Fetch ALL passengers for the flight to show occupied seats
    all_rows = db.execute("SELECT * FROM passengers WHERE flight_no = ?", (flight["flight_no"],)).fetchall()
    
    # 2. Convert sqlite3.Row objects to dictionaries to use .get() method safely
    full_pax_list = [dict(row) for row in all_rows]
    
    # 3. Build the visual seat map using the dictionary list
    seat_rows = build_seat_rows(flight["vehicle_type"], full_pax_list)
    
    # 4. Calculate available seats for the dropdown menu
    occupied_set = set(p["seat_no"] for p in full_pax_list if p.get("seat_no"))
    all_seat_map = build_seat_map(flight["vehicle_type"])
    available_seats = [s for s in all_seat_map if s["seat_no"] not in occupied_set]

    return render_template("manage_booking.html", 
                           user=current_user(), pnr=pnr, flight=flight, 
                           passengers=passengers, seat_rows=seat_rows, 
                           available_seats=available_seats)

    # Data for rendering
    all_flight_pax = db.execute("SELECT seat_no FROM passengers WHERE flight_no = ?", (flight["flight_no"],)).fetchall()
    occupied_set = set(p["seat_no"] for p in all_flight_pax if p["seat_no"])
    
    seat_rows = build_seat_rows(flight["vehicle_type"], all_flight_pax)
    
    all_seat_map = build_seat_map(flight["vehicle_type"])
    available_seats = [s for s in all_seat_map if s["seat_no"] not in occupied_set]

    return render_template("manage_booking.html", 
                           user=current_user(), pnr=pnr, flight=flight, 
                           passengers=passengers, seat_rows=seat_rows, 
                           available_seats=available_seats)

# ---------- ROSTER / ADMIN ROUTES ----------

@app.route("/flight/<flight_no>/generate_roster")
@login_required()
def generate_roster(flight_no):
    """Generates roster for Admin/Operator (Simplified logic)."""
    db = get_db()
    flight = db.execute("SELECT * FROM flights WHERE flight_no=?", (flight_no,)).fetchone()
    
    passengers = [dict(p) for p in db.execute("SELECT * FROM passengers WHERE flight_no=?", (flight_no,)).fetchall()]
    
    # Mock Pilots/Cabin
    pilots = [dict(p) for p in db.execute("SELECT * FROM pilots LIMIT 2")]
    cabin = [dict(a) for a in db.execute("SELECT * FROM attendants LIMIT 4")]

    roster = {
        "flight": dict(flight),
        "pilots": pilots,
        "cabin": cabin,
        "passengers": passengers
    }
    
    cur = db.execute("INSERT INTO rosters (flight_no, created_at, data_json) VALUES (?,?,?)",
               (flight_no, utc_now_iso(), json.dumps(roster)))
    db.commit()
    
    return redirect(url_for("view_roster_by_id", roster_id=cur.lastrowid))

@app.route("/flight/<flight_no>/roster")
@login_required()
def view_latest_roster(flight_no):
    """View the most recent roster for a flight."""
    db = get_db()
    flight = db.execute("SELECT * FROM flights WHERE flight_no=?", (flight_no,)).fetchone()
    if not flight: return "Flight not found"

    row = db.execute("SELECT * FROM rosters WHERE flight_no=? ORDER BY created_at DESC LIMIT 1", (flight_no,)).fetchone()
    if not row:
        flash("No roster found.", "warning")
        return redirect(url_for("flight_search"))

    roster = json.loads(row["data_json"])
    # Ensure visual map works by building rows
    seat_rows = build_seat_rows(flight["vehicle_type"], roster["passengers"])
    
    return render_template("roster.html", user=current_user(), flight=flight, 
                           pilots=roster["pilots"], cabin=roster["cabin"], 
                           passengers=roster["passengers"], seat_rows=seat_rows, roster_id=row["id"])

@app.route("/flight/<flight_no>/rosters")
@login_required()
def list_saved_rosters(flight_no):
    """List history of rosters."""
    db = get_db()
    flight = db.execute("SELECT * FROM flights WHERE flight_no=?", (flight_no,)).fetchone()
    rosters = db.execute("SELECT id, created_at FROM rosters WHERE flight_no=? ORDER BY created_at DESC", (flight_no,)).fetchall()
    return render_template("rosters_list.html", user=current_user(), flight=flight, rosters=rosters)

@app.route("/roster/<int:roster_id>")
@login_required()
def view_roster_by_id(roster_id):
    """View a specific historical roster."""
    db = get_db()
    row = db.execute("SELECT * FROM rosters WHERE id=?", (roster_id,)).fetchone()
    roster = json.loads(row["data_json"])
    flight = db.execute("SELECT * FROM flights WHERE flight_no=?", (row["flight_no"],)).fetchone()
    
    seat_rows = build_seat_rows(flight["vehicle_type"], roster["passengers"])
    return render_template("roster.html", user=current_user(), flight=flight, 
                           pilots=roster["pilots"], cabin=roster["cabin"], 
                           passengers=roster["passengers"], seat_rows=seat_rows, roster_id=roster_id)

@app.route("/export/<flight_no>.json")
@login_required()
def export_roster(flight_no):
    db = get_db()
    row = db.execute("SELECT data_json FROM rosters WHERE flight_no = ? ORDER BY created_at DESC LIMIT 1", (flight_no,)).fetchone()
    if not row: return jsonify({"error": "No roster"}), 404
    return jsonify(json.loads(row["data_json"]))

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0", port=5001)