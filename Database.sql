----------------------------------------------------
-- USERS
----------------------------------------------------
CREATE TABLE Users (
    user_id       TEXT PRIMARY KEY,     -- UUID 
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT DEFAULT 'user',  -- admin/user
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);


----------------------------------------------------
-- FLIGHT INFORMATION DATABASE
----------------------------------------------------

-- AIRPORTS
CREATE TABLE Airports (
    airport_code CHAR(3) PRIMARY KEY,
    country      TEXT NOT NULL,
    city         TEXT NOT NULL,
    name         TEXT NOT NULL
);

-- VEHICLE TYPES (Planes)
CREATE TABLE VehicleTypes (
    vehicle_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    seat_capacity   INTEGER NOT NULL,
    seat_plan_json  TEXT NOT NULL
);

-- FLIGHTS
CREATE TABLE Flights (
    flight_number   CHAR(6) PRIMARY KEY,
    date_time       TEXT NOT NULL,
    duration_min    INTEGER NOT NULL,
    distance_km     INTEGER NOT NULL,
    source_airport  CHAR(3) NOT NULL,
    dest_airport    CHAR(3) NOT NULL,
    vehicle_type_id INTEGER NOT NULL,
    FOREIGN KEY (source_airport) REFERENCES Airports(airport_code),
    FOREIGN KEY (dest_airport)   REFERENCES Airports(airport_code),
    FOREIGN KEY (vehicle_type_id) REFERENCES VehicleTypes(vehicle_type_id)
);

-- SHARED FLIGHT INFORMATION
CREATE TABLE SharedFlights (
    shared_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_number      CHAR(6) NOT NULL,
    shared_flight_no   CHAR(6) NOT NULL,
    shared_company     TEXT NOT NULL,
    connecting_flight  CHAR(6),
    FOREIGN KEY (flight_number) REFERENCES Flights(flight_number)
);


----------------------------------------------------
-- PASSENGER INFORMATION DATABASE
----------------------------------------------------

-- PASSENGERS
CREATE TABLE Passengers (
    passenger_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_number  CHAR(6) NOT NULL,
    name           TEXT NOT NULL,
    age            INTEGER NOT NULL,
    gender         TEXT CHECK(gender IN ('M','F','X')) NOT NULL,
    nationality    TEXT NOT NULL,
    seat_type      TEXT CHECK(seat_type IN ('business','economy','infant')) NOT NULL,
    seat_number    TEXT,                -- may be NULL
    parent_id      INTEGER,             -- only for infants
    FOREIGN KEY (flight_number) REFERENCES Flights(flight_number),
    FOREIGN KEY (parent_id) REFERENCES Passengers(passenger_id)
);

-- PASSENGER AFFILIATIONS (for seating-near-each-other requirement)
CREATE TABLE PassengerAffiliations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    passenger_id  INTEGER NOT NULL,
    affiliated_id INTEGER NOT NULL,
    FOREIGN KEY (passenger_id) REFERENCES Passengers(passenger_id),
    FOREIGN KEY (affiliated_id) REFERENCES Passengers(passenger_id)
);
