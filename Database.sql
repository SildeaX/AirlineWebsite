from datetime import datetime, date, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query, status
from pydantic import BaseModel, constr
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session

"""
# -------------------------
# Database configuration
# -------------------------
"""

DATABASE_URL = "sqlite:///./flights.db"  # change to Postgres/MySQL if you want

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""
# -------------------------
# ORM model (Flight table)
# -------------------------
"""

class Flight(Base):
    _tablename_ = "flights"

    id = Column(Integer, primary_key=True, index=True)
    flight_number = Column(String(10), unique=True, index=True, nullable=False)
    departure_airport = Column(String(5), index=True, nullable=False)
    arrival_airport = Column(String(5), index=True, nullable=False)
    departure_time = Column(DateTime, index=True, nullable=False)
    arrival_time = Column(DateTime, nullable=False)
    status = Column(String(20), default="SCHEDULED", nullable=False)
    aircraft_type = Column(String(30), nullable=True)
    gate = Column(String(10), nullable=True)


"""# create tables on first run"""
Base.metadata.create_all(bind=engine)

"""
# -------------------------
# Pydantic schemas
# -------------------------
"""

class FlightBase(BaseModel):
    flight_number: constr(min_length=2, max_length=10)
    departure_airport: constr(min_length=3, max_length=5)
    arrival_airport: constr(min_length=3, max_length=5)
    departure_time: datetime
    arrival_time: datetime
    status: Optional[str] = "SCHEDULED"
    aircraft_type: Optional[str] = None
    gate: Optional[str] = None


class FlightCreate(FlightBase):
    pass


class FlightUpdate(BaseModel):
    departure_airport: Optional[constr(min_length=3, max_length=5)] = None
    arrival_airport: Optional[constr(min_length=3, max_length=5)] = None
    departure_time: Optional[datetime] = None
    arrival_time: Optional[datetime] = None
    status: Optional[str] = None
    aircraft_type: Optional[str] = None
    gate: Optional[str] = None


class FlightOut(FlightBase):
    id: int

    class Config:
        orm_mode = True

"""
# -------------------------
# FastAPI app
# -------------------------
"""

app = FastAPI(
    title="Flight Information API",
    version="1.0.0",
    description="Provides flight information for the Flight Roster Management System.",
)


"""
# -------------------------
# Health check (for monitoring)
# -------------------------
"""

@app.get("/health", tags=["system"])
def health_check():
    """
    Simple health endpoint so the main system
    can check if the API is alive.
    """
    return {"status": "ok"}


"""
# -------------------------
# CRUD Endpoints
# -------------------------
"""

@app.post(
    "/flights",
    response_model=FlightOut,
    status_code=status.HTTP_201_CREATED,
    tags=["flights"],
)
def create_flight(flight: FlightCreate, db: Session = Depends(get_db)):
  """  # Enforce unique flight_number"""
    existing = db.query(Flight).filter_by(flight_number=flight.flight_number).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Flight with this flight_number already exists.",
        )

    db_flight = Flight(**flight.dict())
    db.add(db_flight)
    db.commit()
    db.refresh(db_flight)
    return db_flight


@app.get(
    "/flights",
    response_model=List[FlightOut],
    tags=["flights"],
)
def list_flights(
    flight_number: Optional[str] = Query(None, description="Exact flight number"),
    departure: Optional[str] = Query(None, description="Departure airport code"),
    destination: Optional[str] = Query(None, description="Arrival airport code"),
    date_: Optional[date] = Query(
        None,
        alias="date",
        description="Date of departure (YYYY-MM-DD)",
    ),
    db: Session = Depends(get_db),
):
    """
    Search flights by flight number, departure, destination or date.
    This directly satisfies FR2 from your requirements.
    """
    query = db.query(Flight)

    if flight_number:
        query = query.filter(Flight.flight_number == flight_number)

    if departure:
        query = query.filter(Flight.departure_airport == departure.upper())

    if destination:
        query = query.filter(Flight.arrival_airport == destination.upper())

    if date_:
       """ # filter flights whose departure_time is on that calendar day"""
        start = datetime.combine(date_, datetime.min.time())
        end = start + timedelta(days=1)
        query = query.filter(Flight.departure_time >= start,
                             Flight.departure_time < end)

    """ You can later add pagination here if needed"""
    flights = query.order_by(Flight.departure_time).all()
    return flights


@app.get(
    "/flights/{flight_id}",
    response_model=FlightOut,
    tags=["flights"],
)
def get_flight(flight_id: int, db: Session = Depends(get_db)):
    flight = db.query(Flight).get(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    return flight


@app.put(
    "/flights/{flight_id}",
    response_model=FlightOut,
    tags=["flights"],
)
def update_flight(
    flight_id: int,
    update: FlightUpdate,
    db: Session = Depends(get_db),
):
    flight = db.query(Flight).get(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")

    for field, value in update.dict(exclude_unset=True).items():
        setattr(flight, field, value)

    db.commit()
    db.refresh(flight)
    return flight


@app.delete(
    "/flights/{flight_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["flights"],
)
def delete_flight(flight_id: int, db: Session = Depends(get_db)):
    flight = db.query(Flight).get(flight_id)
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    db.delete(flight)
    db.commit()
    return None