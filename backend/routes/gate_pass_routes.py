"""
gate_pass_routes.py – authority queue and security verification.

Listing and decisions always use the signed-in account's own unit.
A client cannot ask for another hostel or department.
"""

from flask import Blueprint, g, jsonify, request

from backend.models.gate_pass import (
    decide,
    get_gate_pass,
    list_all,
    list_for_unit,
    record_verification,
)
from backend.routes.auth_routes import require_roles

gate_pass_bp = Blueprint("gate_pass_bp", __name__)

_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


def _decision_response(result, err):
    if err == "not_found":
        return jsonify({"error": "Gate pass not found"}), 404
    if err == "forbidden":
        return jsonify({"error": "You can only decide gate passes for your own hostel or department"}), 403
    if err == "conflict":
        return jsonify({"error": "This gate pass was already approved or rejected"}), 409
    return jsonify({"gate_pass": result})


@gate_pass_bp.route("/mine", methods=["GET"])
@require_roles("HOSTEL", "DEPARTMENT")
def mine():
    status = (request.args.get("status") or "").strip().upper()
    if status and status not in _STATUSES:
        return jsonify({"error": "Unknown status"}), 400
    # The gate office sees every request. Other desks stay limited to their unit.
    if g.account.get("id") == "AUTH-GATE":
        passes = list_all(status or None)
    else:
        passes = list_for_unit(g.account["unit_id"], status or None)
    grouped = {"PENDING": [], "APPROVED": [], "REJECTED": []}
    for item in passes:
        grouped[item["status"]].append(item)
    return jsonify({
        "account": g.account,
        "pending": grouped["PENDING"],
        "approved": grouped["APPROVED"],
        "rejected": grouped["REJECTED"],
    })


@gate_pass_bp.route("/<gp_id>/approve", methods=["POST"])
@require_roles("HOSTEL", "DEPARTMENT")
def approve(gp_id):
    note = ""
    if request.is_json:
        note = (request.get_json(silent=True) or {}).get("note") or ""
    result, err = decide(gp_id, g.account, "APPROVED", note)
    return _decision_response(result, err)


@gate_pass_bp.route("/<gp_id>/reject", methods=["POST"])
@require_roles("HOSTEL", "DEPARTMENT")
def reject(gp_id):
    note = ""
    if request.is_json:
        note = (request.get_json(silent=True) or {}).get("note") or ""
    result, err = decide(gp_id, g.account, "REJECTED", note)
    return _decision_response(result, err)


@gate_pass_bp.route("/verify", methods=["POST"])
@require_roles("SECURITY")
def verify():
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    body = request.get_json(silent=True) or {}
    gate_pass_id = (body.get("gate_pass_id") or "").strip()
    if not gate_pass_id:
        return jsonify({"error": "Enter a gate pass id"}), 400
    row = get_gate_pass(gate_pass_id)
    if not row:
        return jsonify({"error": "No gate pass with that id"}), 404
    gate_pass = record_verification(row, g.account)
    if gate_pass["valid_for_entry"]:
        verdict = "VALID — this truck may enter."
    else:
        verdict = f"NOT VALID — this gate pass is {gate_pass['status']}. Do not allow entry."
    return jsonify({
        "gate_pass": gate_pass,
        "valid_for_entry": gate_pass["valid_for_entry"],
        "verdict": verdict,
    })
