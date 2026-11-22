"""
authority.py – hostel, department, and security accounts.

Passwords are hashed before they are stored. API responses use
public_authority(), which never includes the hash.
"""

import os
import time

from werkzeug.security import check_password_hash, generate_password_hash

from backend.database.db import execute, fetchone
from backend.services.campus import UNITS

# Demo passwords live only on the server. Override with environment variables.
# They are never written into HTML or JavaScript.
_DEFAULT_PASSWORDS = {
    "hostel-1": "Hostel1-Approve",
    "hostel-3": "Hostel3-Approve",
    "hostel-12": "Hostel12-Approve",
    "cse": "Cse-Approve",
    "sjmsom": "Sjmsom-Approve",
    "library": "Library-Approve",
    "estate": "Estate-Approve",
    "guesthouse": "Guest-Approve",
    "security": "Security-Verify",
    "gate": "gate123",
}

_ACCOUNTS = [
    {"id": "AUTH-HOSTEL-1", "unit_id": "hostel-1", "username": "hostel1.warden", "display_name": "Hostel-1 Warden", "role": "HOSTEL"},
    {"id": "AUTH-HOSTEL-3", "unit_id": "hostel-3", "username": "hostel3.warden", "display_name": "Hostel-3 Warden", "role": "HOSTEL"},
    {"id": "AUTH-HOSTEL-12", "unit_id": "hostel-12", "username": "hostel12.warden", "display_name": "Hostel-12 Warden", "role": "HOSTEL"},
    {"id": "AUTH-CSE", "unit_id": "cse", "username": "cse.office", "display_name": "CSE Department Office", "role": "DEPARTMENT"},
    {"id": "AUTH-SJMSOM", "unit_id": "sjmsom", "username": "sjmsom.office", "display_name": "SJMSOM Department Office", "role": "DEPARTMENT"},
    {"id": "AUTH-LIBRARY", "unit_id": "library", "username": "library.office", "display_name": "Central Library Office", "role": "DEPARTMENT"},
    {"id": "AUTH-ESTATE", "unit_id": "estate", "username": "estate.office", "display_name": "Estate Office", "role": "DEPARTMENT"},
    {"id": "AUTH-GUESTHOUSE", "unit_id": "guesthouse", "username": "guesthouse.office", "display_name": "Guest House Office", "role": "DEPARTMENT"},
    {"id": "AUTH-SECURITY", "unit_id": "security", "username": "security.gate", "display_name": "Campus Security", "role": "SECURITY"},
    {"id": "AUTH-GATE", "unit_id": None, "username": "gate", "display_name": "Gate Office", "role": "DEPARTMENT"},
]

_UNITS = {u["id"]: u for u in UNITS}
_DUMMY_HASH = generate_password_hash("gate-pass-dummy-not-a-login")


def public_authority(row: dict) -> dict:
    """Fields safe to send to the browser."""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "unit_id": row.get("unit_id"),
        "unit_name": row.get("unit_name"),
        "unit_type": row.get("unit_type"),
    }


def _password_for(key: str) -> str:
    env_name = "GATEPASS_PASSWORD_" + key.upper().replace("-", "_")
    return os.environ.get(env_name) or _DEFAULT_PASSWORDS[key]


def seed_authorities():
    """Insert missing accounts. Existing password hashes are left as they are."""
    now = int(time.time())
    for spec in _ACCOUNTS:
        if fetchone("SELECT id FROM authorities WHERE username=?", (spec["username"],)):
            continue
        if spec["id"] == "AUTH-GATE":
            unit_id, unit_name, unit_type = None, "All hostels and departments", "gate"
            secret_key = "gate"
        elif spec["role"] == "SECURITY":
            unit_id, unit_name, unit_type = None, "Campus Security", "security"
            secret_key = "security"
        else:
            unit = _UNITS[spec["unit_id"]]
            unit_id, unit_name, unit_type = unit["id"], unit["name"], unit["type"]
            secret_key = spec["unit_id"]
        execute(
            """INSERT INTO authorities(
                   id, username, password_hash, display_name, role,
                   unit_id, unit_name, unit_type, active, created_at
               ) VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (
                spec["id"],
                spec["username"],
                generate_password_hash(_password_for(secret_key)),
                spec["display_name"],
                spec["role"],
                unit_id,
                unit_name,
                unit_type,
                now,
            ),
        )


def get_authority(authority_id: str) -> dict | None:
    return fetchone("SELECT * FROM authorities WHERE id=?", (authority_id,))


def authenticate(username: str, password: str) -> dict | None:
    """Return the public account, or None. Unknown users take the same hash check."""
    username = (username or "").strip().lower()
    password = password or ""
    row = fetchone("SELECT * FROM authorities WHERE username=?", (username,))
    if not row or not row.get("active"):
        check_password_hash(_DUMMY_HASH, password)
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return public_authority(row)
