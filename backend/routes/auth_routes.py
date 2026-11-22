"""
auth_routes.py – session login for hostel, department, and security staff.
"""

from functools import wraps

from flask import Blueprint, g, jsonify, request, session

from backend.models.authority import authenticate, get_authority, public_authority

auth_bp = Blueprint("auth_bp", __name__)


def current_account():
    authority_id = session.get("authority_id")
    if not authority_id:
        return None
    row = get_authority(authority_id)
    if not row or not row.get("active"):
        session.clear()
        return None
    return public_authority(row)


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            account = current_account()
            if not account:
                return jsonify({"error": "Sign in required"}), 401
            if roles and account["role"] not in roles:
                return jsonify({"error": "You are not allowed to do that"}), 403
            g.account = account
            return fn(*args, **kwargs)
        return wrapped
    return decorator


@auth_bp.route("/login", methods=["POST"])
def login():
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    body = request.get_json(silent=True) or {}
    account = authenticate(body.get("username"), body.get("password"))
    if not account:
        return jsonify({"error": "Invalid username or password"}), 401
    session.clear()
    session["authority_id"] = account["id"]
    return jsonify({"account": account})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    return jsonify({"account": current_account()})
