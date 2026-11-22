"""Gate pass approval: who may decide, and what security may treat as valid."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_fd, _db_path = tempfile.mkstemp(prefix="gatepass-", suffix=".db")
os.close(_fd)
os.environ["TRUCK_DB_PATH"] = _db_path
os.environ["FLASK_SECRET_KEY"] = "test-secret-key"

from backend.app import app  # noqa: E402
from backend.database.db import execute, fetchall, fetchone  # noqa: E402
from backend.models.authority import _DEFAULT_PASSWORDS  # noqa: E402
from backend.models.gate_pass import create_for_booking, get_by_booking  # noqa: E402


def fake_route(waypoints, truck_type="small"):
    leg = {
        "distance_m": 1500.0,
        "duration_s": 240.0,
        "geojson": {"type": "LineString", "coordinates": [[72.91, 19.13], [72.92, 19.14]]},
    }
    legs = max(len(waypoints) - 1, 1)
    return {
        "distance_m": 1500.0 * legs,
        "duration_s": 240.0 * legs,
        "geojson": leg["geojson"],
        "legs": [leg for _ in range(legs)],
    }


ROOT = Path(__file__).resolve().parents[1]


class GatePassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def setUp(self):
        execute("DELETE FROM gate_pass_audit")
        execute("DELETE FROM gate_passes")
        execute("DELETE FROM booking_stops")
        execute("DELETE FROM bookings")
        execute("UPDATE vehicles SET status='AVAILABLE', assigned_booking=NULL")
        self.hostel = app.test_client()
        self.other = app.test_client()
        self.dept = app.test_client()
        self.security = app.test_client()

    def _login(self, client, username, password):
        res = client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, res.get_json())
        body = res.get_json()
        self.assertNotIn("password", body["account"])
        self.assertNotIn("password_hash", body["account"])
        self.assertNotIn(password, res.get_data(as_text=True))
        return body["account"]

    def _identity(self, unit_id="hostel-1", category="Student", purpose="hostel_shift"):
        return {
            "booked_by": "Riya Shah",
            "person_category": category,
            "unit": {"id": unit_id, "name": "Hostel-1" if unit_id == "hostel-1" else unit_id, "type": "hostel" if unit_id.startswith("hostel") else "department"},
            "purpose": purpose,
            "purpose_label": "Shifting hostel belongings",
            "purpose_note": "room 214",
        }

    def _open_pass(self, booking_id="BKG-TEST01", unit_id="hostel-1", pickup="IIT Bombay Main Gate", drop="VMCC"):
        snapshot = {
            "id": booking_id,
            "pickup": pickup,
            "drop": drop,
            "truck_type": "light",
            "num_trucks": 1,
            "truck_mix": [{"type": "light", "label": "Light Truck", "count": 1}],
            "assigned_vehicle": None,
        }
        execute(
            """INSERT INTO bookings(id, pickup, "drop", weight_kg, truck_type, num_trucks, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (booking_id, pickup, drop, 400, "light", 1, "PENDING", 1),
        )
        campus = {"entry_gate": "IIT Bombay Main Gate", "entry_slot": "morning", "purpose": "hostel_shift"}
        return create_for_booking(snapshot, self._identity(unit_id), campus)

    def test_login_rejects_bad_password_and_unknown_user(self):
        bad = self.client.post("/api/auth/login", json={"username": "hostel1.warden", "password": "nope"})
        self.assertEqual(bad.status_code, 401)
        missing = self.client.post("/api/auth/login", json={"username": "nobody", "password": "nope"})
        self.assertEqual(missing.status_code, 401)
        self.assertIsNone(self.client.get("/api/auth/me").get_json()["account"])

    def test_authority_sees_only_its_unit(self):
        own = self._open_pass("BKG-OWN")
        self._open_pass("BKG-OTHER", unit_id="hostel-3")
        self._login(self.hostel, "hostel1.warden", "Hostel1-Approve")
        listed = self.hostel.get("/api/gatepass/mine?unit_id=hostel-3")
        self.assertEqual(listed.status_code, 200)
        body = listed.get_json()
        ids = [item["id"] for item in body["pending"]]
        self.assertEqual(ids, [own["id"]])
        self.assertEqual(body["approved"], [])
        self.assertEqual(body["rejected"], [])
        self.assertNotIn("password_hash", listed.get_data(as_text=True))

    def test_gate_office_sees_and_approves_every_unit(self):
        hostel = self._open_pass("BKG-H1", unit_id="hostel-1")
        dept = self._open_pass("BKG-CSE", unit_id="cse")
        gate = app.test_client()
        self._login(gate, "gate", "gate123")
        listed = gate.get("/api/gatepass/mine")
        self.assertEqual(listed.status_code, 200)
        ids = {item["id"] for item in listed.get_json()["pending"]}
        self.assertEqual(ids, {hostel["id"], dept["id"]})
        approved = gate.post(f"/api/gatepass/{dept['id']}/approve", json={"note": "Cleared"})
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.get_json()["gate_pass"]["status"], "APPROVED")
        self.assertEqual(approved.get_json()["gate_pass"]["approving_authority"], "Gate Office")

    def test_hostel_cannot_approve_another_hostel_or_a_department(self):
        own = self._open_pass("BKG-H1", unit_id="hostel-1")
        other = self._open_pass("BKG-H3", unit_id="hostel-3")
        self._login(self.other, "hostel3.warden", "Hostel3-Approve")
        denied = self.other.post(f"/api/gatepass/{own['id']}/approve", json={})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(get_by_booking("BKG-H1")["status"], "PENDING")
        attempt = fetchone(
            "SELECT action FROM gate_pass_audit WHERE gate_pass_id=? AND action='UNAUTHORIZED_ATTEMPT'",
            (own["id"],),
        )
        self.assertIsNotNone(attempt)

        self._login(self.dept, "cse.office", "Cse-Approve")
        dept_denied = self.dept.post(f"/api/gatepass/{own['id']}/approve", json={})
        self.assertEqual(dept_denied.status_code, 403)
        self.assertEqual(get_by_booking("BKG-H1")["status"], "PENDING")

        allowed = self.other.post(f"/api/gatepass/{other['id']}/reject", json={"note": "Wrong date"})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        rejected = allowed.get_json()["gate_pass"]
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["rejecting_authority"], "Hostel-3 Warden")
        self.assertFalse(rejected["valid_for_entry"])
        self.assertTrue(rejected["decided_at"])
        self.assertEqual(get_by_booking("BKG-H3")["decision_note"], "Wrong date")

    def test_approve_once_records_authority_and_blocks_a_second_decision(self):
        row = self._open_pass("BKG-OK")
        anon = self.client.post(f"/api/gatepass/{row['id']}/approve", json={})
        self.assertEqual(anon.status_code, 401)
        self.assertEqual(get_by_booking("BKG-OK")["status"], "PENDING")

        self._login(self.hostel, "hostel1.warden", "Hostel1-Approve")
        first = self.hostel.post(f"/api/gatepass/{row['id']}/approve", json={"note": "Checked with the warden"})
        self.assertEqual(first.status_code, 200, first.get_json())
        approved = first.get_json()["gate_pass"]
        self.assertEqual(approved["status"], "APPROVED")
        self.assertTrue(approved["valid_for_entry"])
        self.assertEqual(approved["approving_authority"], "Hostel-1 Warden")
        self.assertEqual(approved["booked_by"], "Riya Shah")
        self.assertEqual(approved["department_or_hostel"], "Hostel-1")
        self.assertEqual(approved["truck_number"], "Pending assignment")

        second = self.hostel.post(f"/api/gatepass/{row['id']}/reject", json={})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(get_by_booking("BKG-OK")["status"], "APPROVED")
        booking = fetchone("SELECT extra_fields FROM bookings WHERE id='BKG-OK'")
        self.assertIn("APPROVED", booking["extra_fields"])
        actions = [r["action"] for r in fetchall(
            "SELECT action FROM gate_pass_audit WHERE gate_pass_id=? ORDER BY id", (row["id"],)
        )]
        self.assertEqual(actions[0], "CREATED")
        self.assertIn("APPROVED", actions)

    def test_security_verification_accepts_only_approved_passes(self):
        row = self._open_pass("BKG-SEC")
        self._login(self.hostel, "hostel1.warden", "Hostel1-Approve")
        self._login(self.security, "security.gate", "Security-Verify")

        blocked = self.hostel.post("/api/gatepass/verify", json={"gate_pass_id": row["id"]})
        self.assertEqual(blocked.status_code, 403)
        guest = app.test_client().post("/api/gatepass/verify", json={"gate_pass_id": row["id"]})
        self.assertEqual(guest.status_code, 401)

        pending = self.security.post("/api/gatepass/verify", json={"gate_pass_id": row["id"]})
        self.assertEqual(pending.status_code, 200)
        self.assertFalse(pending.get_json()["valid_for_entry"])
        self.assertTrue(pending.get_json()["verdict"].startswith("NOT VALID"))

        self.hostel.post(f"/api/gatepass/{row['id']}/approve", json={})
        valid = self.security.post("/api/gatepass/verify", json={"gate_pass_id": row["id"].lower()})
        self.assertTrue(valid.get_json()["valid_for_entry"])
        self.assertEqual(valid.get_json()["gate_pass"]["approving_authority"], "Hostel-1 Warden")
        self.assertTrue(valid.get_json()["verdict"].startswith("VALID"))

        missing = self.security.post("/api/gatepass/verify", json={"gate_pass_id": "GP-DOESNOTEXIST"})
        self.assertEqual(missing.status_code, 404)
        views = fetchall(
            "SELECT action FROM gate_pass_audit WHERE gate_pass_id=? AND action='VERIFIED'",
            (row["id"],),
        )
        self.assertGreaterEqual(len(views), 2)

    def test_security_cannot_approve_and_duplicate_pass_is_not_created(self):
        row = self._open_pass("BKG-DUP")
        self._login(self.security, "security.gate", "Security-Verify")
        denied = self.security.post(f"/api/gatepass/{row['id']}/approve", json={})
        self.assertEqual(denied.status_code, 403)
        again = create_for_booking(
            {"id": "BKG-DUP", "pickup": "A", "drop": "B", "truck_type": "light", "num_trucks": 1},
            self._identity(),
            {},
        )
        self.assertEqual(again["id"], row["id"])
        created = fetchall(
            "SELECT id FROM gate_pass_audit WHERE gate_pass_id=? AND action='CREATED'",
            (row["id"],),
        )
        self.assertEqual(len(created), 1)

    @patch("backend.routes.driver_routes.start_to_pickup")
    @patch("backend.routes.driver_routes.start_multi_stop_simulation")
    @patch("backend.routes.driver_routes.get_route_info", return_value={"geojson": None, "distance_m": 1000, "duration_s": 120})
    @patch("backend.routes.user_routes.get_multi_stop_route", side_effect=fake_route)
    def test_campus_booking_creates_a_pending_pass_and_city_booking_does_not(self, _route, _info, _multi, _pickup):
        missing = self.client.post("/api/user/book", json={
            "pickup": "IIT Bombay Main Gate",
            "drop": "VMCC",
            "weight_kg": 400,
            "stops": [],
        })
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(fetchone("SELECT COUNT(*) AS n FROM bookings")["n"], 0)

        campus = self.client.post("/api/user/book", json={
            "pickup": "IIT Bombay Main Gate",
            "drop": "VMCC",
            "weight_kg": 400,
            "stops": [],
            "booked_by": "Arjun Mehta",
            "person_category": "Professor",
            "unit_id": "cse",
            "purpose": "lab_equipment",
            "purpose_note": "moving a server rack",
        })
        self.assertEqual(campus.status_code, 200, campus.get_json())
        booking = campus.get_json()["booking"]
        gp = booking["gate_pass"]
        self.assertEqual(gp["status"], "PENDING")
        self.assertEqual(gp["booked_by"], "Arjun Mehta")
        self.assertEqual(gp["person_category"], "Professor")
        self.assertEqual(gp["department_or_hostel"], "Computer Science and Engineering")
        self.assertEqual(gp["unit_type"], "department")
        self.assertEqual(gp["booking_id"], booking["id"])
        self.assertIn("Light", gp["truck_details"])
        self.assertFalse(gp["valid_for_entry"])

        self._login(self.hostel, "hostel1.warden", "Hostel1-Approve")
        hidden = self.hostel.get("/api/gatepass/mine")
        self.assertEqual(hidden.get_json()["pending"], [])
        self._login(self.dept, "cse.office", "Cse-Approve")
        visible = self.dept.get("/api/gatepass/mine")
        self.assertEqual(visible.get_json()["pending"][0]["id"], gp["id"])

        city = self.client.post("/api/user/book", json={
            "pickup": "Colaba",
            "drop": "Fort",
            "weight_kg": 400,
            "stops": [],
        })
        self.assertEqual(city.status_code, 200, city.get_json())
        self.assertNotIn("gate_pass", city.get_json()["booking"])

        narrow = self.client.post("/api/user/book", json={
            "pickup": "Hostel-12",
            "drop": "VMCC",
            "weight_kg": 5000,
            "stops": [],
            "booked_by": "Arjun Mehta",
            "person_category": "Staff",
            "unit_id": "hostel-12",
            "purpose": "furniture",
            "entry_gate": "Market Gate",
            "entry_slot": "evening",
        })
        self.assertEqual(narrow.status_code, 400)
        self.assertIn("narrow", narrow.get_json()["error"].lower())

    @patch("backend.routes.driver_routes.start_to_pickup")
    @patch("backend.routes.driver_routes.start_multi_stop_simulation")
    @patch("backend.routes.driver_routes.get_route_info", return_value={"geojson": None})
    def test_assigned_truck_number_is_copied_onto_the_pass(self, _route, _multi, _pickup):
        booked = None
        with patch("backend.routes.user_routes.get_multi_stop_route", side_effect=fake_route):
            res = self.client.post("/api/user/book", json={
                "pickup": "IIT Bombay Main Gate",
                "drop": "Guest House",
                "weight_kg": 400,
                "stops": [],
                "booked_by": "Neha Iyer",
                "person_category": "Research Scholar",
                "unit_id": "guesthouse",
                "purpose": "personal",
            })
            booked = res.get_json()["booking"]
        self.assertEqual(booked["status"], "ACCEPTED")
        self.assertEqual(booked["assigned_vehicle"], "LIGHT-1")
        row = get_by_booking(booked["id"])
        self.assertIn("LIGHT-1", row["truck_number"])
        self.assertIn("Light Truck 1", row["truck_number"])

    def test_demo_passwords_are_not_in_the_frontend(self):
        frontend = ROOT / "frontend"
        blobs = []
        for path in frontend.rglob("*"):
            if path.suffix.lower() in {".html", ".js", ".css"} and path.is_file():
                blobs.append(path.read_text(encoding="utf-8"))
        combined = "\n".join(blobs)
        for password in _DEFAULT_PASSWORDS.values():
            self.assertNotIn(password, combined)


if __name__ == "__main__":
    unittest.main()
