"""
db.py  –  SQLite database layer
Thread-safe per-thread connections using threading.local().
Provides schema init, seed data, and raw connection access.
"""

import sqlite3, threading, json, os
from pathlib import Path

def db_path() -> Path:
    """SQLite file. TRUCK_DB_PATH overrides it for tests."""
    override = os.environ.get("TRUCK_DB_PATH")
    return Path(override) if override else Path(__file__).parent / "app.db"


DB_PATH = db_path()
_local  = threading.local()


# ─────────────────────────────────────────────────────────────
#  Connection management
# ─────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    """Return the per-thread SQLite connection, creating it if needed."""
    path = str(db_path())
    if not hasattr(_local, "conn") or _local.conn is None or getattr(_local, "path", None) != path:
        if getattr(_local, "conn", None) is not None:
            _local.conn.close()
        _local.conn = sqlite3.connect(path, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")   # concurrent read/write
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.path = path
    return _local.conn


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = get_conn()
    cur  = conn.execute(sql, params)
    conn.commit()
    return cur


def fetchall(sql: str, params: tuple = ()) -> list:
    cur = get_conn().execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    cur = get_conn().execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────
#  Schema
# ─────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id               TEXT PRIMARY KEY,
    name             TEXT,
    truck_type       TEXT DEFAULT 'small',
    lat              REAL,
    lng              REAL,
    status           TEXT DEFAULT 'AVAILABLE',
    assigned_booking TEXT
);

CREATE TABLE IF NOT EXISTS locations (
    name  TEXT PRIMARY KEY,
    lat   REAL,
    lng   REAL
);

CREATE TABLE IF NOT EXISTS bookings (
    id                 TEXT PRIMARY KEY,
    pickup             TEXT,
    "drop"             TEXT,
    weight_kg          REAL  DEFAULT 0,
    truck_type         TEXT,
    num_trucks         INTEGER DEFAULT 1,
    distance_km        REAL,
    eta_mins           REAL,
    cost               REAL,
    halt_charge        REAL  DEFAULT 0,
    status             TEXT  DEFAULT 'PENDING',
    assigned_vehicle   TEXT,
    created_at         INTEGER,
    driver_loaded      INTEGER DEFAULT 0,
    user_loaded        INTEGER DEFAULT 0,
    pickup_lat         REAL,
    pickup_lng         REAL,
    drop_lat           REAL,
    drop_lng           REAL,
    route_geojson      TEXT,
    to_pickup_geojson  TEXT,
    to_drop_geojson    TEXT,
    leg_geojsons       TEXT,
    extra_fields       TEXT
);

CREATE TABLE IF NOT EXISTS booking_stops (
    booking_id  TEXT,
    stop_index  INTEGER,
    name        TEXT,
    lat         REAL,
    lng         REAL,
    PRIMARY KEY (booking_id, stop_index)
);

CREATE TABLE IF NOT EXISTS authorities (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('HOSTEL', 'DEPARTMENT', 'SECURITY')),
    unit_id       TEXT,
    unit_name     TEXT,
    unit_type     TEXT,
    active        INTEGER DEFAULT 1,
    created_at    INTEGER
);

CREATE TABLE IF NOT EXISTS gate_passes (
    id               TEXT PRIMARY KEY,
    booking_id       TEXT UNIQUE NOT NULL,
    booked_by        TEXT NOT NULL,
    person_category  TEXT NOT NULL,
    unit_id          TEXT NOT NULL,
    unit_name        TEXT NOT NULL,
    unit_type        TEXT NOT NULL,
    purpose          TEXT NOT NULL,
    purpose_label    TEXT,
    purpose_note     TEXT,
    entry_gate       TEXT,
    entry_slot       TEXT,
    truck_type       TEXT,
    num_trucks       INTEGER,
    truck_details    TEXT,
    truck_number     TEXT,
    pickup           TEXT,
    drop_location    TEXT,
    status           TEXT NOT NULL DEFAULT 'PENDING'
                     CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    decided_by       TEXT,
    decided_by_name  TEXT,
    decided_at       INTEGER,
    decision_note    TEXT,
    created_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS gate_pass_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gate_pass_id  TEXT NOT NULL,
    action        TEXT NOT NULL,
    actor_id      TEXT,
    actor_name    TEXT,
    actor_role    TEXT,
    detail        TEXT,
    created_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gate_passes_unit_status ON gate_passes(unit_id, status);
CREATE INDEX IF NOT EXISTS idx_gate_audit_pass ON gate_pass_audit(gate_pass_id);
"""


def _ensure_location_columns(conn: sqlite3.Connection):
    """Add campus metadata without rebuilding the existing locations table."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(locations)")}
    if "zone" not in cols:
        conn.execute("ALTER TABLE locations ADD COLUMN zone TEXT DEFAULT 'city'")
    if "heavy_ok" not in cols:
        conn.execute("ALTER TABLE locations ADD COLUMN heavy_ok INTEGER DEFAULT 1")
    conn.commit()


def init_db():
    """Initialise schema and seed default data."""
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    _ensure_location_columns(conn)
    _seed_data(conn)
    from backend.models.authority import seed_authorities
    from backend.models.vehicle import release_finished_vehicles
    seed_authorities()
    release_finished_vehicles()
    print("[DB] SQLite database ready:", db_path())


# ─────────────────────────────────────────────────────────────
#  Seed initial data (idempotent)
# ─────────────────────────────────────────────────────────────
_SEED_VEHICLES = [
    ("LIGHT-1", "Light Truck 1", "light", 19.125148, 72.916627, "AVAILABLE", None),
    ("SMALL-1", "Small Truck 1", "small", 19.130000, 72.919000, "AVAILABLE", None),
    ("BIG-1",   "Big Truck 1",   "big",   19.127000, 72.912000, "AVAILABLE", None),
    ("BIG-2",   "Campus Heavy 2", "big",  19.125400, 72.916200, "AVAILABLE", None),
    ("LIGHT-2", "Colaba Light",  "light", 18.922000, 72.831000, "AVAILABLE", None),
    ("SMALL-2", "Bandra Small",  "small", 19.054400, 72.840600, "AVAILABLE", None),
    ("BIG-3",   "Thane Heavy",   "big",   19.218300, 72.978100, "AVAILABLE", None),
]

_SEED_LOCATIONS = [
    # Narrow street constraint testing locations
    ("Hostel-12",            19.135516, 72.905630),
    ("Narrow Street",        19.131000, 72.915000),
    ("Market Road",          19.129000, 72.914000),
    
    # South Mumbai
    ("Colaba",              18.9067, 72.8147),
    ("Fort",                18.9322, 72.8339),
    ("Churchgate",          18.9322, 72.8264),
    ("Marine Drive",        18.9440, 72.8211),
    ("Malabar Hill",        18.9548, 72.7985),
    ("Tardeo",              18.9688, 72.8136),
    ("Mahalaxmi",           18.9827, 72.8089),
    ("Worli",               19.0169, 72.8197),
    ("Lower Parel",         18.9953, 72.8300),
    ("Prabhadevi",          19.0166, 72.8258),
    ("Dadar",               19.0178, 72.8478),
    ("Mahim",               19.0402, 72.8439),
    ("Sion",                19.0390, 72.8619),

    # Western Suburbs
    ("Bandra",              19.0596, 72.8295),
    ("Khar",                19.0691, 72.8360),
    ("Santacruz",           19.0805, 72.8420),
    ("Vile Parle",          19.0968, 72.8517),
    ("Andheri",             19.1136, 72.8697),
    ("Juhu",                19.1075, 72.8263),
    ("Jogeshwari",          19.1334, 72.8452),
    ("Goregaon",            19.1643, 72.8496),
    ("Malad",               19.1860, 72.8486),
    ("Kandivali",           19.2044, 72.8524),
    ("Borivali",            19.2290, 72.8573),
    ("Dahisar",             19.2501, 72.8593),

    # Eastern Suburbs
    ("Kurla",               19.0728, 72.8795),
    ("Chembur",             19.0520, 72.8996),
    ("Vidyavihar",          19.0792, 72.8966),
    ("Ghatkopar",           19.0856, 72.9080),
    ("Vikhroli",            19.1111, 72.9288),
    ("Kanjurmarg",          19.1286, 72.9255),
    ("Powai",               19.1176, 72.9060),
    ("Bhandup",             19.1439, 72.9322),
    ("Nahur",               19.1557, 72.9439),
    ("Mulund",              19.1726, 72.9425),
    
    # Extended Region
    ("Thane",               19.2183, 72.9781),
    ("Navi Mumbai",         19.0330, 73.0297),
    ("IIT Bombay Main Gate", 19.125212, 72.916564),
    ("Y-Point Gate",         19.12980,  72.91540),
    ("Market Gate",          19.13140,  72.90890),
    ("Convocation Hall",     19.13190,  72.91510),
    ("VMCC",                 19.13070,  72.91690),
    ("Central Library",      19.13270,  72.91630),
    ("KReSIT / CSE",         19.13240,  72.91600),
    ("SJMSOM",               19.13150,  72.91310),
    ("Guest House",          19.12840,  72.91410),
    ("Lakeside",             19.13590,  72.91040),
    ("Hostel-1",             19.13420,  72.90680),
    ("Hostel-3",             19.13610,  72.90720),
]


def _seed_data(conn: sqlite3.Connection):
    for v in _SEED_VEHICLES:
        conn.execute(
            "INSERT OR IGNORE INTO vehicles(id,name,truck_type,lat,lng,status,assigned_booking) VALUES(?,?,?,?,?,?,?)",
            v,
        )
    for loc in _SEED_LOCATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO locations(name,lat,lng) VALUES(?,?,?)",
            loc,
        )

    from backend.services.campus import ZONE_UPDATES
    for name, (zone, heavy_ok) in ZONE_UPDATES.items():
        conn.execute(
            "UPDATE locations SET zone=?, heavy_ok=? WHERE name=?",
            (zone, heavy_ok, name),
        )
    conn.execute("UPDATE locations SET zone='city' WHERE zone IS NULL OR zone=''")
    conn.commit()


# ─────────────────────────────────────────────────────────────
#  Coordinate cleanup after trip completes
# ─────────────────────────────────────────────────────────────
def clear_route_data(booking_id: str):
    """
    Remove all geojson coordinate blobs from a completed booking.
    Keeps all trip summary fields (cost, distance, truck_type, etc.).
    """
    execute(
        """UPDATE bookings
           SET route_geojson=NULL, to_pickup_geojson=NULL,
               to_drop_geojson=NULL, leg_geojsons=NULL
           WHERE id=?""",
        (booking_id,),
    )
    print(f"[DB] Route coordinate data cleared for {booking_id}")
