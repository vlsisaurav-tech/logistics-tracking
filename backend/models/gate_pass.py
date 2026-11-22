"""
gate_pass.py – in-gate pass requests tied to a truck booking.

Status moves only from PENDING to APPROVED or REJECTED, and only when the
signed-in authority belongs to that pass's hostel or department.
"""

import time
import uuid
from datetime import datetime

from backend.database.db import execute, fetchall, fetchone
from backend.services.campus import PURPOSE_LABEL

_OPEN = "PENDING"
_FINAL = {"APPROVED", "REJECTED"}


def _iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts)).isoformat(timespec="seconds")


def _clean_note(note, limit=500) -> str:
    text = " ".join((note or "").split())
    return text[:limit]


def describe_trucks(booking: dict, vehicle_label=None):
    mix = booking.get("truck_mix") or []
    if mix:
        parts = []
        for item in mix:
            label = item.get("label") or item.get("type") or "truck"
            parts.append(f"{item.get('count', 1)}× {label}")
        summary = ", ".join(parts)
    else:
        count = booking.get("num_trucks") or 1
        kind = booking.get("truck_type") or "truck"
        summary = f"{count}× {kind}"
    number = vehicle_label or booking.get("assigned_vehicle") or "Pending assignment"
    return summary, number


def serialize(row: dict) -> dict | None:
    if not row:
        return None
    status = row["status"]
    return {
        "id": row["id"],
        "booking_id": row["booking_id"],
        "booked_by": row["booked_by"],
        "person_category": row["person_category"],
        "department_or_hostel": row["unit_name"],
        "unit_id": row["unit_id"],
        "unit_name": row["unit_name"],
        "unit_type": row["unit_type"],
        "purpose": row["purpose"],
        "purpose_label": row.get("purpose_label") or PURPOSE_LABEL.get(row["purpose"], row["purpose"]),
        "purpose_note": row.get("purpose_note") or "",
        "entry_gate": row.get("entry_gate") or "",
        "entry_slot": row.get("entry_slot") or "",
        "truck_type": row.get("truck_type"),
        "num_trucks": row.get("num_trucks"),
        "truck_details": row.get("truck_details") or "",
        "truck_number": row.get("truck_number") or "Pending assignment",
        "pickup": row.get("pickup") or "",
        "drop": row.get("drop_location") or "",
        "status": status,
        "approval_status": status,
        "valid_for_entry": status == "APPROVED",
        "approving_authority": row.get("decided_by_name") if status == "APPROVED" else None,
        "rejecting_authority": row.get("decided_by_name") if status == "REJECTED" else None,
        "decided_by": row.get("decided_by"),
        "decided_by_name": row.get("decided_by_name"),
        "decided_at": _iso(row.get("decided_at")),
        "decision_note": row.get("decision_note") or "",
        "created_at": _iso(row.get("created_at")),
    }


def audit(gate_pass_id: str, action: str, actor: dict | None, detail: str = ""):
    actor = actor or {}
    execute(
        """INSERT INTO gate_pass_audit(
               gate_pass_id, action, actor_id, actor_name, actor_role, detail, created_at
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            gate_pass_id,
            action,
            actor.get("id"),
            actor.get("display_name") or actor.get("booked_by"),
            actor.get("role") or actor.get("person_category"),
            detail[:500],
            int(time.time()),
        ),
    )


def get_gate_pass(gate_pass_id: str) -> dict | None:
    if not gate_pass_id:
        return None
    return fetchone("SELECT * FROM gate_passes WHERE id=?", (gate_pass_id.strip().upper(),))


def get_by_booking(booking_id: str) -> dict | None:
    if not booking_id:
        return None
    return fetchone("SELECT * FROM gate_passes WHERE booking_id=?", (booking_id,))


def attach(booking: dict | None) -> dict | None:
    """Add the gate pass, when one exists, onto a booking dict."""
    if not booking:
        return booking
    row = get_by_booking(booking.get("id"))
    if row:
        booking["gate_pass"] = serialize(row)
    return booking


def list_all(status: str | None = None) -> list:
    if status:
        rows = fetchall(
            "SELECT * FROM gate_passes WHERE status=? ORDER BY created_at DESC",
            (status,),
        )
    else:
        rows = fetchall("SELECT * FROM gate_passes ORDER BY created_at DESC")
    return [serialize(row) for row in rows]


def list_for_unit(unit_id: str, status: str | None = None) -> list:
    if status:
        rows = fetchall(
            """SELECT * FROM gate_passes
               WHERE unit_id=? AND status=?
               ORDER BY created_at DESC""",
            (unit_id, status),
        )
    else:
        rows = fetchall(
            "SELECT * FROM gate_passes WHERE unit_id=? ORDER BY created_at DESC",
            (unit_id,),
        )
    return [serialize(row) for row in rows]


def _sync_booking_status(booking_id: str, status: str, gate_pass_id: str):
    from backend.models.booking import update_booking
    update_booking(booking_id, {
        "gate_pass_id": gate_pass_id,
        "gate_pass_status": status,
    })


def create_for_booking(snapshot: dict, identity: dict, campus: dict) -> dict:
    """Open one PENDING pass for a booking. A second call returns the existing pass."""
    existing = get_by_booking(snapshot["id"])
    if existing:
        return existing

    gate_id = None
    for _ in range(5):
        candidate = "GP-" + uuid.uuid4().hex[:8].upper()
        if not fetchone("SELECT id FROM gate_passes WHERE id=?", (candidate,)):
            gate_id = candidate
            break
    if not gate_id:
        raise RuntimeError("Could not allocate a gate pass id")

    unit = identity["unit"]
    truck_details, truck_number = describe_trucks(snapshot)
    now = int(time.time())
    execute(
        """INSERT INTO gate_passes(
               id, booking_id, booked_by, person_category,
               unit_id, unit_name, unit_type,
               purpose, purpose_label, purpose_note,
               entry_gate, entry_slot,
               truck_type, num_trucks, truck_details, truck_number,
               pickup, drop_location, status, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            gate_id,
            snapshot["id"],
            identity["booked_by"],
            identity["person_category"],
            unit["id"],
            unit["name"],
            unit["type"],
            identity["purpose"],
            identity["purpose_label"],
            identity.get("purpose_note") or "",
            campus.get("entry_gate") or "",
            campus.get("entry_slot") or "",
            snapshot.get("truck_type"),
            snapshot.get("num_trucks") or 1,
            truck_details,
            truck_number,
            snapshot.get("pickup") or "",
            snapshot.get("drop") or "",
            _OPEN,
            now,
        ),
    )
    audit(
        gate_id,
        "CREATED",
        {
            "booked_by": identity["booked_by"],
            "person_category": identity["person_category"],
            "role": identity["person_category"],
            "display_name": identity["booked_by"],
        },
        f"booking {snapshot['id']} for {unit['name']}",
    )
    _sync_booking_status(snapshot["id"], _OPEN, gate_id)
    return get_gate_pass(gate_id)


def _is_gate_office(account: dict) -> bool:
    return account.get("id") == "AUTH-GATE"


def _owns(account: dict, row: dict) -> bool:
    if _is_gate_office(account):
        return True
    if account.get("role") == "HOSTEL" and row.get("unit_type") != "hostel":
        return False
    if account.get("role") == "DEPARTMENT" and row.get("unit_type") != "department":
        return False
    if account.get("role") not in ("HOSTEL", "DEPARTMENT"):
        return False
    return account.get("unit_id") == row.get("unit_id")


def decide(gate_pass_id: str, account: dict, new_status: str, note: str = ""):
    """
    Approve or reject a PENDING pass.
    Returns (serialized pass or None, error code).
    error code is one of: not_found, forbidden, conflict.
    """
    if new_status not in _FINAL:
        return None, "forbidden"
    row = get_gate_pass(gate_pass_id)
    if not row:
        return None, "not_found"
    if not _owns(account, row):
        audit(
            row["id"],
            "UNAUTHORIZED_ATTEMPT",
            account,
            f"tried to set {new_status}",
        )
        return None, "forbidden"
    if row["status"] != _OPEN:
        audit(row["id"], "CONFLICT_ATTEMPT", account, f"already {row['status']}")
        return None, "conflict"

    cleaned = _clean_note(note)
    now = int(time.time())
    if _is_gate_office(account):
        cur = execute(
            """UPDATE gate_passes
               SET status=?, decided_by=?, decided_by_name=?, decided_at=?, decision_note=?
               WHERE id=? AND status='PENDING'""",
            (
                new_status,
                account["id"],
                account["display_name"],
                now,
                cleaned,
                row["id"],
            ),
        )
    else:
        cur = execute(
            """UPDATE gate_passes
               SET status=?, decided_by=?, decided_by_name=?, decided_at=?, decision_note=?
               WHERE id=? AND status='PENDING' AND unit_id=? AND unit_type=?""",
            (
                new_status,
                account["id"],
                account["display_name"],
                now,
                cleaned,
                row["id"],
                account["unit_id"],
                row["unit_type"],
            ),
        )
    if cur.rowcount != 1:
        fresh = get_gate_pass(row["id"])
        audit(row["id"], "CONFLICT_ATTEMPT", account, f"update missed, now {fresh['status'] if fresh else 'missing'}")
        return None, "conflict"

    audit(row["id"], new_status, account, cleaned)
    _sync_booking_status(row["booking_id"], new_status, row["id"])
    return serialize(get_gate_pass(row["id"])), None


def sync_assigned_vehicle(booking_id: str, vehicle_id: str, vehicle_name: str | None):
    """Copy the truck assigned by a driver onto the pass, if one exists."""
    row = get_by_booking(booking_id)
    if not row or not vehicle_id:
        return None
    label = vehicle_id if not vehicle_name or vehicle_name == vehicle_id else f"{vehicle_id} ({vehicle_name})"
    execute(
        "UPDATE gate_passes SET truck_number=? WHERE id=?",
        (label, row["id"]),
    )
    audit(
        row["id"],
        "VEHICLE_ASSIGNED",
        {"id": vehicle_id, "display_name": vehicle_name or vehicle_id, "role": "DRIVER"},
        label,
    )
    return serialize(get_gate_pass(row["id"]))


def record_verification(row: dict, account: dict) -> dict:
    audit(row["id"], "VERIFIED", account, row["status"])
    return serialize(row)
