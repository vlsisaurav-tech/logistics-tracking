"""
user_routes.py  –  User-facing API
Supports:
  • Multi-stop estimates and bookings
  • Truck type auto-detection
  • Intermediate stop confirmation and halt tracking
"""

from flask import Blueprint, request, jsonify
from backend.services.route_optimizer import get_multi_stop_route, get_route_info
from backend.services.cost_calculator import get_cost_breakdown, calculate_cost, HALT_RATE_PER_HOUR
from backend.models.booking import create_booking, list_bookings, get_booking, update_booking
from backend.database.db import fetchall
from backend.services.campus import assess_trip, public_rules, unit_by_id, validate_campus_identity
import time, uuid

user_bp = Blueprint("user_bp", __name__)


def _get_locations_dict() -> dict:
    """Fetch locations from SQLite as {name: {lat, lng, zone, heavy_ok}} dict."""
    rows = fetchall("SELECT name, lat, lng, zone, heavy_ok FROM locations")
    return {
        r["name"]: {
            "lat": r["lat"],
            "lng": r["lng"],
            "zone": r.get("zone") or "city",
            "heavy_ok": r.get("heavy_ok", 1),
        }
        for r in rows
    }


def _with_unit_requester(payload):
    """The selected hostel or department is the requesting unit."""
    data = dict(payload or {})
    unit = unit_by_id(data.get("unit_id"))
    if unit:
        data["requester"] = unit["name"]
    return data


def _campus_error(campus_err):
    return jsonify({"error": " ".join(campus_err["errors"])}), 400


def _present(booking):
    from backend.models.gate_pass import attach
    from backend.services.dispatch import attach_shipment
    return attach_shipment(attach(booking))


def _quote(payload, breakdown, pickup, drop, stops, weight, truck_type, locs, loaded_km):
    """Reprice from the nearest legal truck and any return or shared load."""
    from backend.database.db import fetchall
    from backend.models.vehicle import get_all_vehicles, release_finished_vehicles
    from backend.services.dispatch import quote_trip
    release_finished_vehicles()

    pending = []
    for row in fetchall(
        "SELECT id, status, weight_kg, pickup_lat, pickup_lng, drop_lat, drop_lng "
        "FROM bookings WHERE status='PENDING'"
    ):
        if row["pickup_lat"] is None or row["drop_lat"] is None:
            continue
        pending.append({
            "id": row["id"],
            "status": row["status"],
            "weight_kg": row["weight_kg"],
            "pickup_coords": (row["pickup_lat"], row["pickup_lng"]),
            "drop_coords": (row["drop_lat"], row["drop_lng"]),
        })
    quoted = quote_trip(
        base_fare=round(breakdown["total_cost"] - (breakdown.get("campus_fee") or 0), 2),
        campus_fee=breakdown.get("campus_fee") or 0,
        truck_type=truck_type,
        num_trucks=breakdown.get("num_trucks") or 1,
        loaded_km=loaded_km,
        pickup_lat=locs[pickup]["lat"],
        pickup_lng=locs[pickup]["lng"],
        drop_lat=locs[drop]["lat"],
        drop_lng=locs[drop]["lng"],
        place_names=[pickup, drop] + list(stops or []),
        weight_kg=weight,
        vehicles=get_all_vehicles(),
        pending=pending,
        vehicle_id=payload.get("vehicle_id"),
        fare_mode=payload.get("fare_mode") or "standard",
    )
    breakdown["total_cost"] = quoted["cost"]
    breakdown["dispatch"] = quoted["dispatch"]
    return quoted


def _apply_campus(payload, names, truck_type, breakdown):
    """Attach gate-pass fields and add the campus fee onto an existing fare."""
    payload = _with_unit_requester(payload)
    locs = _get_locations_dict()
    zones = {name: info.get("zone", "city") for name, info in locs.items()}
    campus = assess_trip(
        names,
        zones,
        truck_type,
        payload.get("purpose"),
        payload.get("entry_gate"),
        payload.get("entry_slot"),
        payload.get("requester"),
    )
    if campus["errors"]:
        return None, campus
    identity, id_errors = validate_campus_identity(payload, campus["campus_trip"])
    if id_errors:
        return None, {"errors": id_errors}
    campus["identity"] = identity
    if identity:
        campus["requester"] = identity["unit"]["name"]
        campus["booked_by"] = identity["booked_by"]
        campus["person_category"] = identity["person_category"]
        campus["unit_id"] = identity["unit"]["id"]
        campus["unit_name"] = identity["unit"]["name"]
        campus["unit_type"] = identity["unit"]["type"]
        campus["purpose_note"] = identity["purpose_note"]
    breakdown["campus_fee"] = campus["campus_fee"]
    breakdown["campus_trip"] = campus["campus_trip"]
    breakdown["needs_pass"] = campus["needs_pass"]
    breakdown["entry_status"] = campus["entry_status"]
    breakdown["total_cost"] = round(breakdown["total_cost"] + campus["campus_fee"], 2)
    return campus, None


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def _resolve_location(name, locations_dict):
    if name not in locations_dict:
        return None
    loc = locations_dict[name]
    return [loc["lng"], loc["lat"]]   # [lng, lat] for routing


def _build_waypoints(pickup, stops, drop, loc_dict):
    """Build an ordered list of [lng,lat] waypoints: pickup → stops → drop."""
    pts = []
    for name in [pickup] + (stops or []) + [drop]:
        ll = _resolve_location(name, loc_dict)
        if ll is None:
            return None, name
        pts.append(ll)
    return pts, None


# ─────────────────────────────────────────────
#  GET /api/user/locations
# ─────────────────────────────────────────────
@user_bp.route("/locations", methods=["GET"])
def get_locations():
    locs = _get_locations_dict()
    return jsonify([
        {"name": k, "lat": v["lat"], "lng": v["lng"], "zone": v["zone"], "heavy_ok": v["heavy_ok"]}
        for k, v in locs.items()
    ])


@user_bp.route("/campus", methods=["GET"])
def campus_info():
    """Gates, purposes, and entry windows for IIT heavy-vehicle bookings."""
    return jsonify(public_rules())


# ─────────────────────────────────────────────
#  POST /api/user/estimate
# ─────────────────────────────────────────────
@user_bp.route("/estimate", methods=["POST"])
def estimate():
    payload  = request.json or {}
    pickup   = payload.get("pickup")
    drop     = payload.get("drop")
    stops    = payload.get("stops", [])          # list of intermediate stop names
    weight   = float(payload.get("weight_kg", 0))
    manual_trucks = payload.get("manual_trucks")

    locs = _get_locations_dict()

    waypoints, bad = _build_waypoints(pickup, stops, drop, locs)
    if waypoints is None:
        return jsonify({"error": f"Unknown location: {bad}"}), 400

    from backend.services.cost_calculator import determine_truck_allocation, get_cost_breakdown
    
    if manual_trucks and any(int(v) > 0 for v in manual_trucks.values()):
        truck_type = "light"
        if int(manual_trucks.get("big", 0)) > 0: truck_type = "big"
        elif int(manual_trucks.get("small", 0)) > 0: truck_type = "small"
    else:
        alloc = determine_truck_allocation(weight)
        truck_type = alloc["type"]

    # ── Compatibility Check: Big Trucks vs Narrow Roads ──
    if truck_type == "big":
        narrow_locations = ["Hostel-12", "Hostel-3", "Narrow Street", "Market Road"]
        all_names = [pickup, drop] + stops
        if any(any(nl in name for nl in narrow_locations) for name in all_names):
            return jsonify({"error": "A Big Truck cannot navigate the narrow streets at your selected locations. Please select a smaller truck."}), 400

    route = get_multi_stop_route(waypoints, truck_type)
    breakdown = get_cost_breakdown(route["distance_m"] / 1000.0, weight,
                                   manual_trucks=manual_trucks)
    campus, campus_err = _apply_campus(payload, [pickup, drop] + stops, truck_type, breakdown)
    if campus_err:
        return _campus_error(campus_err)
    loaded_km = round(route["distance_m"] / 1000.0, 3)
    quoted = _quote(payload, breakdown, pickup, drop, stops, weight, truck_type, locs, loaded_km)

    legs_info = [
        {
            "from": ([pickup] + stops)[i],
            "to":   (stops + [drop])[i],
            "distance_km": round(leg["distance_m"] / 1000.0, 3),
            "eta_mins":    round(leg["duration_s"]  / 60.0,   1),
        }
        for i, leg in enumerate(route["legs"])
    ]

    return jsonify({
        "distance_km":   round(route["distance_m"] / 1000.0, 3),
        "eta_mins":      round(route["duration_s"]  / 60.0,   1),
        "cost":          quoted["cost"],
        "breakdown":     breakdown,
        "nearby":        quoted["nearby"],
        "dispatch":      quoted["dispatch"],
        "legs":          legs_info,
        "route_geojson": route["geojson"],
        "campus": {
            "campus_trip": campus["campus_trip"],
            "needs_pass": campus["needs_pass"],
            "entry_status": campus["entry_status"],
            "campus_fee": campus["campus_fee"],
            "entry_gate": campus["entry_gate"],
            "entry_slot": campus["entry_slot"],
            "purpose": campus["purpose"],
            "requester": campus["requester"],
            "booked_by": campus.get("booked_by") or "",
            "person_category": campus.get("person_category") or "",
            "unit_id": campus.get("unit_id") or "",
            "unit_name": campus.get("unit_name") or "",
            "gate_pass_required": campus["campus_trip"],
        },
    })


# ─────────────────────────────────────────────
#  POST /api/user/book
# ─────────────────────────────────────────────
@user_bp.route("/book", methods=["POST"])
def book():
    payload = request.json or {}
    pickup  = payload.get("pickup")
    drop    = payload.get("drop")
    stops   = payload.get("stops", [])
    weight  = float(payload.get("weight_kg", 0))
    manual_trucks = payload.get("manual_trucks")

    locs = _get_locations_dict()

    waypoints, bad = _build_waypoints(pickup, stops, drop, locs)
    if waypoints is None:
        return jsonify({"error": f"Unknown location: {bad}"}), 400

    from backend.services.cost_calculator import determine_truck_allocation, get_cost_breakdown
    
    if manual_trucks and any(int(v) > 0 for v in manual_trucks.values()):
        truck_type = "light"
        if int(manual_trucks.get("big", 0)) > 0: truck_type = "big"
        elif int(manual_trucks.get("small", 0)) > 0: truck_type = "small"
        num_trucks = sum(int(v) for v in manual_trucks.values())
    else:
        alloc = determine_truck_allocation(weight)
        truck_type = alloc["type"]
        num_trucks = alloc["num_trucks"]

    # ── Compatibility Check: Big Trucks vs Narrow Roads ──
    if truck_type == "big":
        narrow_locations = ["Hostel-12", "Hostel-3", "Narrow Street", "Market Road"]
        all_names = [pickup, drop] + stops
        if any(any(nl in name for nl in narrow_locations) for name in all_names):
            return jsonify({"error": "A Big Truck cannot navigate the narrow streets at your selected locations. Please select a smaller truck."}), 400

    route      = get_multi_stop_route(waypoints, truck_type)
    breakdown  = get_cost_breakdown(route["distance_m"] / 1000.0, weight,
                                    manual_trucks=manual_trucks)
    campus, campus_err = _apply_campus(payload, [pickup, drop] + stops, truck_type, breakdown)
    if campus_err:
        return _campus_error(campus_err)
    loaded_km = round(route["distance_m"] / 1000.0, 3)
    quoted = _quote(payload, breakdown, pickup, drop, stops, weight, truck_type, locs, loaded_km)
    dispatch = quoted["dispatch"]

    # Build stop metadata list
    all_names   = [pickup] + stops + [drop]
    stops_meta  = []
    for i, name in enumerate(stops):
        loc = locs[name]
        stops_meta.append({
            "index":  i,
            "name":   name,
            "coords": [loc["lat"], loc["lng"]],
            "status": "pending",
        })

    # Per-leg geojson dict  leg_0_geojson … leg_N_geojson
    leg_geojsons = {f"leg_{i}_geojson": leg["geojson"] for i, leg in enumerate(route["legs"])}

    pickup_loc = locs[pickup]
    drop_loc   = locs[drop]

    booking_id = f"BKG-{str(uuid.uuid4())[:8]}"
    booking = {
        "id":            booking_id,
        "user_id":       payload.get("user_id", "guest"),
        "status":        "PENDING",
        "pickup":        pickup,
        "drop":          drop,
        "pickup_coords": [locs[pickup]["lat"], locs[pickup]["lng"]],
        "drop_coords":   [locs[drop]["lat"], locs[drop]["lng"]],
        "stops":         stops_meta,
        "weight_kg":     weight,
        "truck_type":    truck_type,
        "num_trucks":    num_trucks,
        "truck_mix":     breakdown.get("truck_mix", []),
        "distance_km":   round(route["distance_m"] / 1000.0, 3),
        "eta_mins":      round(route["duration_s"]  / 60.0,   1),
        "cost":          quoted["cost"],
        "halt_charge":   0.0,
        "preferred_vehicle": dispatch.get("vehicle_id"),
        "preferred_vehicle_name": dispatch.get("vehicle_name"),
        "empty_km":      dispatch.get("empty_km"),
        "owner_cost":    dispatch.get("owner_cost"),
        "owner_earning": dispatch.get("owner_earning"),
        "fare_mode":     dispatch.get("fare_mode"),
        "fare_reason":   dispatch.get("reason") or "",
        "deadhead_charge": dispatch.get("deadhead_charge"),
        "route_geojson": route["geojson"],
        "purpose":       campus["purpose"],
        "purpose_note":  campus.get("purpose_note") or "",
        "entry_gate":    campus["entry_gate"],
        "entry_slot":    campus["entry_slot"],
        "requester":     campus["requester"],
        "booked_by":     campus.get("booked_by") or "",
        "person_category": campus.get("person_category") or "",
        "unit_id":       campus.get("unit_id") or "",
        "unit_name":     campus.get("unit_name") or "",
        "unit_type":     campus.get("unit_type") or "",
        "campus_trip":   campus["campus_trip"],
        "needs_pass":    campus["needs_pass"],
        "entry_status":  campus["entry_status"],
        "campus_fee":    campus["campus_fee"],
        "assigned_vehicle": None,
        "created_at":    int(time.time()),
        "driver_loaded": False,
        "user_loaded":   False,
    }
    booking.update(leg_geojsons)

    identity = campus.get("identity")
    snapshot = {
        "id": booking_id,
        "pickup": pickup,
        "drop": drop,
        "truck_type": truck_type,
        "num_trucks": num_trucks,
        "truck_mix": breakdown.get("truck_mix", []),
        "assigned_vehicle": None,
    }

    from backend.models.booking import create_booking
    create_booking(booking)
    if campus["campus_trip"] and identity:
        from backend.models.gate_pass import create_for_booking
        create_for_booking(snapshot, identity, campus)

    # The reserved truck leaves as soon as the booking is confirmed.
    if dispatch.get("vehicle_id"):
        from backend.routes.driver_routes import _do_accept
        _do_accept(booking_id, dispatch["vehicle_id"])

    full = _present(get_booking(booking_id))
    return jsonify({"booking": full})
# ─────────────────────────────────────────────
#  GET /api/user/bookings
# ─────────────────────────────────────────────
@user_bp.route("/bookings", methods=["GET"])
def bookings():
    return jsonify({"bookings": [_present(b) for b in list_bookings()]})


# ─────────────────────────────────────────────
#  GET /api/user/booking/<bid>
# ─────────────────────────────────────────────
@user_bp.route("/booking/<bid>", methods=["GET"])
def booking_get(bid):
    b = get_booking(bid)
    if not b:
        return jsonify({"error": "not found"}), 404
    return jsonify({"booking": _present(b)})


# ─────────────────────────────────────────────
#  POST /api/user/confirm_loaded   (pickup confirm)
# ─────────────────────────────────────────────
@user_bp.route("/confirm_loaded", methods=["POST"])
def user_confirm_loaded():
    payload    = request.json or {}
    booking_id = payload.get("booking_id")
    if not booking_id:
        return jsonify({"error": "booking_id required"}), 400
    b = get_booking(booking_id)
    if not b:
        return jsonify({"error": "not found"}), 404

    update_booking(booking_id, {"user_loaded": True})
    b2 = get_booking(booking_id)
    if b2.get("driver_loaded") and b2.get("user_loaded"):
        update_booking(booking_id, {"status": "LOADED"})
        # If multi-stop, do nothing here – simulator drives the flow
        if not b2.get("stops"):
            from backend.services.simulator import start_to_drop
            start_to_drop(booking_id)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
#  POST /api/user/confirm_stop/<bid>/<stop_idx>
# ─────────────────────────────────────────────
@user_bp.route("/confirm_stop/<bid>/<int:stop_idx>", methods=["POST"])
def confirm_stop(bid, stop_idx):
    """User confirms cargo loaded at intermediate stop stop_idx."""
    b = get_booking(bid)
    if not b:
        return jsonify({"error": "not found"}), 404
    update_booking(bid, {f"user_stop_{stop_idx}_loaded": True})
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
#  POST /api/user/cancel   (cancel booking before load)
# ─────────────────────────────────────────────
@user_bp.route("/cancel", methods=["POST"])
def cancel_booking():
    payload    = request.json or {}
    booking_id = payload.get("booking_id")
    if not booking_id:
        return jsonify({"error": "booking_id required"}), 400
    
    b = get_booking(booking_id)
    if not b:
        return jsonify({"error": "not found"}), 404
    
    # Only allow cancel before truck is loaded and en route
    if b.get("status") in ("LOADED", "COMPLETED", "DELIVERED") or b.get("status").startswith("AT_STOP"):
        return jsonify({"error": "Cannot cancel after cargo is loaded and en route"}), 400
        
    update_booking(booking_id, {"status": "CANCELLED"})
    
    # If a vehicle was assigned, free it up
    vid = b.get("assigned_vehicle")
    if vid:
        from backend.models.vehicle import update_vehicle
        update_vehicle(vid, {"status": "AVAILABLE", "assigned_booking": None})
        
    return jsonify({"ok": True})
