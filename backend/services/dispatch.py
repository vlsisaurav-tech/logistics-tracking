"""
Nearest-truck matching, a fare that keeps the owner's margin, and
shipment milestones derived from the trip the driver is already running.
"""

import math
import re

from backend.services.cost_calculator import TRUCK_CONFIG

NARROW_PLACES = ("Hostel-12", "Hostel-3", "Narrow Street", "Market Road")
MIN_MARGIN = 0.18
CITY_SPEED_KMH = 28.0
ASSUMED_EMPTY_KM = 5.0
RETURN_WITHIN_KM = 6.0
SHARED_WITHIN_KM = 3.0
RETURN_OFF = 0.12
SHARED_OFF = 0.20

# What it costs the owner to roll a kilometre, empty or loaded.
OWNER_PER_KM = {
    "light": {"empty": 8.0, "loaded": 12.0},
    "small": {"empty": 14.0, "loaded": 22.0},
    "big":   {"empty": 22.0, "loaded": 36.0},
}
# What the user pays for the empty run to the pickup. A nearer truck costs less.
DEADHEAD_PER_KM = {"light": 6.0, "small": 10.0, "big": 14.0}


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


def route_is_narrow(names) -> bool:
    return any(any(place in (name or "") for place in NARROW_PLACES) for name in names)


def rank_trucks(vehicles, pickup_lat, pickup_lng, truck_type) -> list:
    """Available trucks of this type, nearest to the pickup first."""
    ranked = []
    for vehicle in vehicles:
        if vehicle.get("status") != "AVAILABLE":
            continue
        if vehicle.get("truck_type") != truck_type:
            continue
        if vehicle.get("lat") is None or vehicle.get("lng") is None:
            continue
        empty = haversine_km(vehicle["lat"], vehicle["lng"], pickup_lat, pickup_lng)
        ranked.append({
            "id": vehicle["id"],
            "name": vehicle.get("name") or vehicle["id"],
            "truck_type": truck_type,
            "lat": vehicle["lat"],
            "lng": vehicle["lng"],
            "empty_km": round(empty, 2),
            "arrival_mins": round(empty / CITY_SPEED_KMH * 60.0, 1),
        })
    ranked.sort(key=lambda truck: (truck["empty_km"], truck["id"]))
    return ranked


def choose_trucks(ranked, count, preferred_id=None) -> list:
    ordered = list(ranked)
    if preferred_id:
        lead = [truck for truck in ordered if truck["id"] == preferred_id]
        rest = [truck for truck in ordered if truck["id"] != preferred_id]
        if lead:
            ordered = lead + rest
    return ordered[:max(int(count or 1), 1)]


def find_offers(pickup_lat, pickup_lng, drop_lat, drop_lng, weight_kg, truck_type, pending) -> dict:
    """A return load or a shared load on a trip that is still waiting."""
    limit = TRUCK_CONFIG.get(truck_type, TRUCK_CONFIG["big"])["max_kg"]
    return_load = None
    shared_load = None
    for other in pending or []:
        if other.get("status") not in (None, "PENDING"):
            continue
        pickup = other.get("pickup_coords")
        drop = other.get("drop_coords")
        if not pickup or not drop:
            continue
        their_pickup = haversine_km(drop_lat, drop_lng, pickup[0], pickup[1])
        their_drop = haversine_km(pickup_lat, pickup_lng, drop[0], drop[1])
        if return_load is None and their_pickup <= RETURN_WITHIN_KM and their_drop <= RETURN_WITHIN_KM:
            return_load = {
                "booking_id": other.get("id"),
                "reason": "A load is waiting near the drop and comes back this way, so the truck is not empty on the return.",
            }
        same_pickup = haversine_km(pickup_lat, pickup_lng, pickup[0], pickup[1])
        same_drop = haversine_km(drop_lat, drop_lng, drop[0], drop[1])
        other_weight = float(other.get("weight_kg") or 0)
        if (shared_load is None and same_pickup <= SHARED_WITHIN_KM and same_drop <= SHARED_WITHIN_KM
                and float(weight_kg) + other_weight <= limit):
            shared_load = {
                "booking_id": other.get("id"),
                "reason": f"Another {other_weight:.0f} kg load is going the same way and fits on this truck.",
                "combined_kg": round(float(weight_kg) + other_weight, 1),
            }
    return {"return_load": return_load, "shared_load": shared_load}


def _owner_cost(truck_type, loaded_km, chosen, count):
    rates = OWNER_PER_KM.get(truck_type, OWNER_PER_KM["big"])
    missing = max(int(count) - len(chosen), 0)
    empty_km = sum(truck["empty_km"] for truck in chosen) + ASSUMED_EMPTY_KM * missing
    owner_cost = empty_km * rates["empty"] + float(loaded_km) * rates["loaded"] * int(count)
    deadhead = empty_km * DEADHEAD_PER_KM.get(truck_type, DEADHEAD_PER_KM["big"])
    return empty_km, owner_cost, deadhead


def price_trip(base_fare, truck_type, loaded_km, chosen, count, fare_mode, offers) -> dict:
    """User fare after the empty run, floored so the owner keeps a margin."""
    empty_km, owner_cost, deadhead = _owner_cost(truck_type, loaded_km, chosen, count)
    list_fare = float(base_fare) + deadhead
    floor = owner_cost * (1.0 + MIN_MARGIN)
    mode = fare_mode if fare_mode in ("return", "shared") else "standard"
    rate = 0.0
    reason = ""
    if mode == "return" and offers.get("return_load"):
        rate = RETURN_OFF
        reason = offers["return_load"]["reason"]
    elif mode == "shared" and offers.get("shared_load"):
        rate = SHARED_OFF
        reason = offers["shared_load"]["reason"]
    else:
        mode = "standard"
    discounted = list_fare * (1.0 - rate)
    fare = max(floor, discounted)
    return {
        "empty_km": round(empty_km, 2),
        "deadhead_charge": round(deadhead, 2),
        "owner_cost": round(owner_cost, 2),
        "margin_floor": round(floor, 2),
        "list_fare": round(list_fare, 2),
        "fare": round(fare, 2),
        "discount": round(max(0.0, list_fare - fare), 2),
        "owner_earning": round(fare - owner_cost, 2),
        "fare_mode": mode,
        "reason": reason,
    }


def quote_trip(*, base_fare, campus_fee, truck_type, num_trucks, loaded_km,
               pickup_lat, pickup_lng, drop_lat, drop_lng, place_names,
               weight_kg, vehicles, pending, vehicle_id=None, fare_mode="standard") -> dict:
    """Price the trip from the trucks that can actually reach the pickup."""
    count = max(int(num_trucks or 1), 1)
    narrow = route_is_narrow(place_names)
    ranked = [] if narrow and truck_type == "big" else rank_trucks(
        vehicles, pickup_lat, pickup_lng, truck_type
    )
    offers = find_offers(pickup_lat, pickup_lng, drop_lat, drop_lng, weight_kg, truck_type, pending)
    fee = float(campus_fee or 0)

    def fare_for(preferred, mode):
        chosen = choose_trucks(ranked, count, preferred)
        priced = price_trip(base_fare, truck_type, loaded_km, chosen, count, mode, offers)
        priced["vehicle_ids"] = [truck["id"] for truck in chosen]
        return priced

    for truck in ranked:
        for mode in ("standard", "return", "shared"):
            priced_for = fare_for(truck["id"], mode)
            truck[f"{mode}_fare"] = round(priced_for["fare"] + fee, 2)
            truck[f"{mode}_earning"] = priced_for["owner_earning"]

    known = {truck["id"] for truck in ranked}
    lead = vehicle_id if vehicle_id in known else (ranked[0]["id"] if ranked else None)
    priced = fare_for(lead, fare_mode)
    customer = round(priced["fare"] + fee, 2)
    savings = 0.0
    if ranked and lead:
        own = next(truck["standard_fare"] for truck in ranked if truck["id"] == lead)
        savings = round(max(0.0, ranked[-1]["standard_fare"] - own), 2)
    name = next((truck["name"] for truck in ranked if truck["id"] == lead), None)
    return {
        "cost": customer,
        "nearby": ranked,
        "dispatch": {
            **priced,
            "vehicle_id": lead,
            "vehicle_name": name,
            "savings_vs_farthest": savings,
            "offers": offers,
            "campus_fee": fee,
        },
    }


def pick_vehicle(vehicles, booking, requested_id):
    """The truck the user hired, if it is still free. Otherwise the next nearest."""
    truck_type = booking.get("truck_type") or "small"
    names = [booking.get("pickup") or "", booking.get("drop") or ""]
    names += [stop.get("name", "") for stop in (booking.get("stops") or [])]
    if route_is_narrow(names) and truck_type == "big":
        return None
    coords = booking.get("pickup_coords") or (None, None)
    ranked = rank_trucks(vehicles, coords[0], coords[1], truck_type) if None not in coords else []
    wanted = [booking.get("preferred_vehicle"), requested_id]
    by_id = {vehicle["id"]: vehicle for vehicle in vehicles}
    for vid in wanted:
        vehicle = by_id.get(vid)
        if vehicle and any(truck["id"] == vid for truck in ranked):
            return vehicle
    if ranked:
        return by_id.get(ranked[0]["id"])
    return by_id.get(requested_id)


def _stop_progress(status, index):
    if status in ("COMPLETED", "DELIVERED"):
        return "done"
    at_stop = re.fullmatch(r"AT_STOP_(\d+)", status or "")
    left_stop = re.fullmatch(r"DEPARTED_STOP_(\d+)", status or "")
    if at_stop:
        current = int(at_stop.group(1))
        if current > index:
            return "done"
        if current == index:
            return "current"
        return "todo"
    if left_stop and int(left_stop.group(1)) >= index:
        return "done"
    return "todo"


def shipment_view(booking, vehicle=None) -> dict:
    """Goods progress, and the minutes still left from where the truck is now."""
    status = booking.get("status") or "PENDING"
    stops = booking.get("stops") or []
    picked = status in ("LOADED", "COMPLETED", "DELIVERED") or bool(
        re.match(r"(AT_STOP|DEPARTED_STOP)_", status)
    )
    labels = {
        "DELIVERED": "Goods delivered",
        "IN_TRANSIT": "Goods are on the way",
        "AT_STOP": "Goods are at a stop",
        "AT_PICKUP": "Truck is at the pickup",
        "TO_PICKUP": "Truck is heading to the pickup",
        "CANCELLED": "Trip cancelled",
        "BOOKED": "Waiting for the reserved truck",
    }
    if status in ("COMPLETED", "DELIVERED"):
        stage = "DELIVERED"
    elif status == "LOADED" or str(status).startswith("DEPARTED_STOP"):
        stage = "IN_TRANSIT"
    elif str(status).startswith("AT_STOP"):
        stage = "AT_STOP"
    elif status == "ARRIVED_DRIVER":
        stage = "AT_PICKUP"
    elif status == "ACCEPTED":
        stage = "TO_PICKUP"
    elif status == "CANCELLED":
        stage = "CANCELLED"
    else:
        stage = "BOOKED"

    milestones = [
        {"id": "booked", "label": "Booked", "state": "done"},
        {
            "id": "to_pickup",
            "label": "Truck heading to pickup",
            "state": "done" if status not in ("PENDING", "ACCEPTED", "CANCELLED") else (
                "current" if status == "ACCEPTED" else "todo"
            ),
        },
        {
            "id": "picked_up",
            "label": "Goods picked up",
            "state": "done" if picked else ("current" if status == "ARRIVED_DRIVER" else "todo"),
        },
    ]
    for index, stop in enumerate(stops):
        milestones.append({
            "id": f"stop_{index}",
            "label": f"Stop {index + 1}: {stop.get('name') or 'Stop'}",
            "state": _stop_progress(status, index),
        })
    milestones.append({
        "id": "delivered",
        "label": "Delivered",
        "state": "done" if stage == "DELIVERED" else "todo",
    })
    if stage == "IN_TRANSIT":
        for item in milestones:
            if item["state"] == "todo" and item["id"] not in ("delivered",) and not item["id"].startswith("stop_"):
                item["state"] = "current"
                break
        else:
            for item in milestones:
                if item["state"] == "todo":
                    item["state"] = "current"
                    break

    remaining = _remaining_mins(booking, vehicle, status, picked, stops)
    truck = None
    if vehicle and vehicle.get("lat") is not None:
        truck = {
            "id": vehicle.get("id"),
            "name": vehicle.get("name"),
            "lat": vehicle.get("lat"),
            "lng": vehicle.get("lng"),
        }
    return {
        "stage": stage,
        "label": labels[stage],
        "milestones": milestones,
        "remaining_mins": remaining,
        "truck": truck,
    }


def _remaining_mins(booking, vehicle, status, picked, stops):
    if status in ("COMPLETED", "DELIVERED"):
        return 0
    if status == "CANCELLED":
        return None
    if not vehicle or vehicle.get("lat") is None:
        return booking.get("eta_mins")
    points = []
    pickup = booking.get("pickup_coords")
    if not picked and pickup:
        points.append(pickup)
    for index, stop in enumerate(stops):
        if _stop_progress(status, index) != "done" and stop.get("coords"):
            points.append(stop["coords"])
    drop = booking.get("drop_coords")
    if drop:
        points.append(drop)
    if not points:
        return 0
    travelled = 0.0
    lat, lng = vehicle["lat"], vehicle["lng"]
    for lat2, lng2 in points:
        travelled += haversine_km(lat, lng, lat2, lng2)
        lat, lng = lat2, lng2
    return round(travelled / CITY_SPEED_KMH * 60.0, 1)


def attach_shipment(booking):
    if not booking:
        return booking
    from backend.models.vehicle import get_vehicle
    vid = booking.get("assigned_vehicle") or booking.get("preferred_vehicle")
    vehicle = get_vehicle(vid) if vid else None
    booking["shipment"] = shipment_view(booking, vehicle)
    return booking
