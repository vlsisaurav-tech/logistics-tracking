"""Nearest truck, two-sided fare, and shipment milestones."""

import unittest

from backend.services.dispatch import (
    pick_vehicle,
    quote_trip,
    shipment_view,
)


def _truck(vid, kind, lat, lng, status="AVAILABLE"):
    return {
        "id": vid, "name": vid, "truck_type": kind, "status": status,
        "lat": lat, "lng": lng,
    }


def _quote(**over):
    data = dict(
        base_fare=200,
        campus_fee=0,
        truck_type="light",
        num_trucks=1,
        loaded_km=5,
        pickup_lat=18.9067,
        pickup_lng=72.8147,
        drop_lat=18.9340,
        drop_lng=72.8330,
        place_names=["Colaba", "Fort"],
        weight_kg=400,
        vehicles=[
            _truck("FAR", "light", 19.20, 72.90),
            _truck("NEAR", "light", 18.91, 72.82),
            _truck("BUSY", "light", 18.90, 72.81, "ON_TRIP"),
            _truck("SMALL", "small", 18.90, 72.81),
        ],
        pending=[],
    )
    data.update(over)
    return quote_trip(**data)


class DispatchTests(unittest.TestCase):
    def test_nearest_free_truck_is_offered_first_and_costs_less(self):
        quoted = _quote()
        ids = [truck["id"] for truck in quoted["nearby"]]
        self.assertEqual(ids, ["NEAR", "FAR"])
        self.assertEqual(quoted["dispatch"]["vehicle_id"], "NEAR")
        self.assertLess(quoted["nearby"][0]["standard_fare"], quoted["nearby"][1]["standard_fare"])
        self.assertGreater(quoted["dispatch"]["savings_vs_farthest"], 0)
        self.assertGreater(quoted["dispatch"]["owner_earning"], 0)

    def test_narrow_route_does_not_offer_a_big_truck(self):
        quoted = _quote(
            truck_type="big",
            place_names=["Hostel-12", "Main Gate"],
            vehicles=[_truck("BIG", "big", 19.13, 72.91)],
        )
        self.assertEqual(quoted["nearby"], [])
        self.assertIsNone(quoted["dispatch"]["vehicle_id"])

    def test_return_fare_stays_above_the_owner_margin(self):
        quoted = _quote(
            fare_mode="return",
            pending=[{
                "id": "BACK",
                "status": "PENDING",
                "weight_kg": 200,
                "pickup_coords": (18.9340, 72.8330),
                "drop_coords": (18.9067, 72.8147),
            }],
        )
        dispatch = quoted["dispatch"]
        self.assertEqual(dispatch["fare_mode"], "return")
        self.assertGreaterEqual(dispatch["fare"], dispatch["margin_floor"])
        self.assertGreater(dispatch["owner_earning"], 0)
        self.assertIn("return", dispatch["reason"])

    def test_shared_load_needs_room_on_the_same_truck(self):
        same = {
            "status": "PENDING",
            "pickup_coords": (18.9067, 72.8147),
            "drop_coords": (18.9340, 72.8330),
        }
        too_heavy = _quote(pending=[{**same, "id": "HEAVY", "weight_kg": 900}])
        self.assertIsNone(too_heavy["dispatch"]["offers"]["shared_load"])
        fits = _quote(fare_mode="shared", pending=[{**same, "id": "LIGHT", "weight_kg": 200}])
        self.assertEqual(fits["dispatch"]["fare_mode"], "shared")
        self.assertLess(fits["cost"], _quote()["cost"])

    def test_accept_uses_the_reserved_truck(self):
        vehicles = [
            _truck("LIGHT-1", "light", 19.12, 72.91),
            _truck("LIGHT-2", "light", 18.92, 72.83),
        ]
        booking = {
            "truck_type": "light",
            "pickup": "Colaba",
            "drop": "Fort",
            "stops": [],
            "pickup_coords": (18.9067, 72.8147),
            "preferred_vehicle": "LIGHT-2",
        }
        chosen = pick_vehicle(vehicles, booking, "LIGHT-1")
        self.assertEqual(chosen["id"], "LIGHT-2")

    def test_shipment_follows_the_goods_and_the_truck(self):
        booking = {
            "status": "LOADED",
            "eta_mins": 40,
            "pickup_coords": (18.90, 72.81),
            "drop_coords": (18.94, 72.84),
            "stops": [{"name": "Fort", "coords": [18.93, 72.83]}],
        }
        moving = shipment_view(booking, {"id": "NEAR", "name": "Near", "lat": 18.935, "lng": 72.835})
        self.assertEqual(moving["stage"], "IN_TRANSIT")
        self.assertEqual(moving["milestones"][2]["state"], "done")
        self.assertLess(moving["remaining_mins"], 15)
        done = shipment_view({**booking, "status": "DELIVERED"}, {"id": "NEAR", "lat": 18.94, "lng": 72.84})
        self.assertEqual(done["remaining_mins"], 0)
        self.assertEqual(done["milestones"][-1]["state"], "done")
        at_stop = shipment_view({**booking, "status": "AT_STOP_0"}, {"id": "NEAR", "lat": 18.93, "lng": 72.83})
        self.assertEqual(at_stop["milestones"][3]["state"], "current")
        self.assertEqual(at_stop["milestones"][3]["label"], "Stop 1: Fort")


if __name__ == "__main__":
    unittest.main()
