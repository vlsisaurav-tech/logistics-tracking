"""
campus.py – IIT Bombay heavy-vehicle campus rules.

Existing city bookings stay unchanged. These helpers only add a gate
pass, an entry window, and a campus fee when a trip touches the campus.
"""

from datetime import datetime

# Official entry points. Heavy vehicles must use one of these.
GATES = [
    "IIT Bombay Main Gate",
    "Y-Point Gate",
    "Market Gate",
]

PURPOSES = [
    {"id": "hostel_shift", "label": "Shifting hostel belongings"},
    {"id": "lab_equipment", "label": "Departmental equipment transportation"},
    {"id": "furniture", "label": "Furniture delivery"},
    {"id": "personal", "label": "Personal belongings transportation"},
    {"id": "construction", "label": "Construction material"},
    {"id": "canteen", "label": "Canteen and mess supplies"},
    {"id": "general", "label": "General campus freight"},
]
PURPOSE_IDS = {p["id"] for p in PURPOSES}
PURPOSE_LABEL = {p["id"]: p["label"] for p in PURPOSES}

# Who is asking, and which hostel or department must approve entry.
CATEGORIES = ["Student", "Professor", "Staff", "Research Scholar"]

# Approval units. Hostels and departments are separate so one cannot sign for the other.
UNITS = [
    {"id": "hostel-1", "name": "Hostel-1", "type": "hostel"},
    {"id": "hostel-3", "name": "Hostel-3", "type": "hostel"},
    {"id": "hostel-12", "name": "Hostel-12", "type": "hostel"},
    {"id": "cse", "name": "Computer Science and Engineering", "type": "department"},
    {"id": "sjmsom", "name": "SJMSOM", "type": "department"},
    {"id": "library", "name": "Central Library", "type": "department"},
    {"id": "estate", "name": "Estate Office", "type": "department"},
    {"id": "guesthouse", "name": "Guest House", "type": "department"},
]
UNIT_BY_ID = {u["id"]: u for u in UNITS}

# Campus security allows heavy vehicles in two daily windows.
SLOTS = [
    {"id": "morning", "label": "Morning window (06:00-09:30)", "start": 6.0, "end": 9.5},
    {"id": "evening", "label": "Evening window (16:30-19:30)", "start": 16.5, "end": 19.5},
]
SLOT_BY_ID = {s["id"]: s for s in SLOTS}

# Flat security charge. Big trucks pay more because they need an escort.
CAMPUS_FEE_LIGHT = 80.0
CAMPUS_FEE_BIG = 250.0

# name, lat, lng, zone, heavy_ok (0 = inner road too narrow for a big truck)
CAMPUS_LOCATIONS = [
    ("IIT Bombay Main Gate", 19.125212, 72.916564, "gate", 1),
    ("Y-Point Gate",          19.12980,  72.91540,  "gate", 1),
    ("Market Gate",           19.13140,  72.90890,  "gate", 1),
    ("Convocation Hall",      19.13190,  72.91510,  "campus", 1),
    ("VMCC",                  19.13070,  72.91690,  "campus", 1),
    ("Central Library",       19.13270,  72.91630,  "campus", 1),
    ("KReSIT / CSE",          19.13240,  72.91600,  "campus", 1),
    ("SJMSOM",                19.13150,  72.91310,  "campus", 1),
    ("Guest House",           19.12840,  72.91410,  "campus", 1),
    ("Lakeside",              19.13590,  72.91040,  "campus", 1),
    ("Hostel-1",              19.13420,  72.90680,  "campus", 1),
    ("Hostel-12",             19.135516, 72.905630, "narrow", 0),
    ("Hostel-3",              19.13610,  72.90720,  "narrow", 0),
    ("Narrow Street",         19.131000, 72.915000, "narrow", 0),
    ("Market Road",           19.129000, 72.914000, "narrow", 0),
]

# Existing rows that should be tagged even if they were seeded earlier.
ZONE_UPDATES = {row[0]: (row[3], row[4]) for row in CAMPUS_LOCATIONS}


def _hour_float(now=None) -> float:
    now = now or datetime.now()
    return now.hour + now.minute / 60.0


def slot_is_open(slot_id: str, now=None) -> bool:
    slot = SLOT_BY_ID.get(slot_id)
    if not slot:
        return False
    hour = _hour_float(now)
    return slot["start"] <= hour <= slot["end"]


def assess_trip(names, zones_by_name, truck_type, purpose, entry_gate, entry_slot, requester):
    """
    Decide whether this trip needs an IIT gate pass.

    zones_by_name: {location name: zone}
    Returns a dict with campus_trip, needs_pass, campus_fee, entry_status, errors.
    """
    touched = []
    for name in names:
        if not name:
            continue
        zone = zones_by_name.get(name, "city")
        if zone in ("campus", "gate", "narrow"):
            touched.append(name)

    campus_trip = len(touched) > 0
    needs_pass = campus_trip and truck_type == "big"
    errors = []

    if needs_pass:
        if purpose not in PURPOSE_IDS:
            errors.append("Choose a campus purpose for this heavy-vehicle booking.")
        if entry_gate not in GATES:
            errors.append("A big truck must enter through Main Gate, Y-Point Gate, or Market Gate.")
        if entry_slot not in SLOT_BY_ID:
            errors.append("Pick a campus entry window: morning or evening.")
        if not (requester or "").strip():
            errors.append("Enter the department, lab, or hostel requesting the vehicle.")

    if truck_type == "big" and needs_pass:
        campus_fee = CAMPUS_FEE_BIG
    elif campus_trip:
        campus_fee = CAMPUS_FEE_LIGHT
    else:
        campus_fee = 0.0

    if needs_pass and entry_slot in SLOT_BY_ID:
        entry_status = "OPEN" if slot_is_open(entry_slot) else "SCHEDULED"
    elif campus_trip:
        entry_status = "OPEN"
    else:
        entry_status = "NOT_REQUIRED"

    return {
        "campus_trip": campus_trip,
        "needs_pass": needs_pass,
        "campus_fee": campus_fee,
        "entry_status": entry_status,
        "touched": touched,
        "errors": errors,
        "purpose": purpose or "",
        "entry_gate": entry_gate or "",
        "entry_slot": entry_slot or "",
        "requester": (requester or "").strip(),
    }


def unit_by_id(unit_id: str):
    return UNIT_BY_ID.get((unit_id or "").strip())


def validate_campus_identity(payload: dict, campus_trip: bool):
    """
    Fields the hostel or department must see before approving entry.
    City trips skip this. Returns (identity dict or None, errors).
    """
    if not campus_trip:
        return None, []

    errors = []
    booked_by = " ".join((payload.get("booked_by") or "").split())
    if len(booked_by) < 2 or len(booked_by) > 80:
        errors.append("Enter the name of the person who booked the truck.")
    category = (payload.get("person_category") or "").strip()
    if category not in CATEGORIES:
        errors.append("Select who is booking: Student, Professor, Staff, or Research Scholar.")
    unit = unit_by_id(payload.get("unit_id"))
    if not unit:
        errors.append("Select the department or hostel that must approve this gate pass.")
    purpose = (payload.get("purpose") or "").strip()
    if purpose not in PURPOSE_IDS:
        errors.append("Select the purpose of this truck booking.")
    note = " ".join((payload.get("purpose_note") or "").split())
    if len(note) > 240:
        errors.append("Keep the purpose details under 240 characters.")
    if errors:
        return None, errors
    return {
        "booked_by": booked_by,
        "person_category": category,
        "unit": unit,
        "purpose": purpose,
        "purpose_label": PURPOSE_LABEL[purpose],
        "purpose_note": note,
    }, []


def public_rules():
    return {
        "gates": GATES,
        "purposes": PURPOSES,
        "categories": CATEGORIES,
        "units": [{"id": u["id"], "name": u["name"], "type": u["type"]} for u in UNITS],
        "slots": [{"id": s["id"], "label": s["label"]} for s in SLOTS],
        "fees": {"campus_access": CAMPUS_FEE_LIGHT, "heavy_escort": CAMPUS_FEE_BIG},
        "note": (
            "A truck that touches the IIT campus needs an in-gate pass approved by the "
            "hostel or department that booked it. Big trucks also need an official gate "
            "and a morning or evening entry window. Narrow hostel lanes still reject big trucks."
        ),
    }
