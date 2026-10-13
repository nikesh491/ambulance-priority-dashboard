
from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, session
)
from datetime import datetime, timezone
from threading import Lock
from functools import wraps

app = Flask(__name__)
app.secret_key = "change-this-to-a-random-secret-key"

lock = Lock()

USERS = {
    "driver": {"username": "driver", "password": "1234"},
    "police": {"username": "police", "password": "1234"}
}

DIRECTIONS = {"NORTH", "SOUTH", "EAST", "WEST"}

ambulance = {
    "ambulance_id": "AMB-001",
    "latitude": 11.0168,
    "longitude": 76.9558,
    "speed": 0,
    "emergency": True,
    "direction": "EAST",
    "junction": "Main Junction",
    "distance_km": 0.8,
    "signal": "GREEN",
    "last_updated": None
}

signals = {
    "NORTH": "RED",
    "SOUTH": "RED",
    "EAST": "GREEN",
    "WEST": "RED"
}


def require_role(role):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                return jsonify(success=False,
                               message="Please sign in with the correct role."), 401
            return function(*args, **kwargs)
        return wrapper
    return decorator


def snapshot():
    with lock:
        return {
            **ambulance,
            "traffic_signals": dict(signals)
        }


@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("role") == "driver":
            return redirect(url_for("driver"))
        if session.get("role") == "police":
            return redirect(url_for("police"))
        return render_template("login.html", error=None)

    role = request.form.get("role", "").lower()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = USERS.get(role)

    if user and username == user["username"] and password == user["password"]:
        session.clear()
        session["role"] = role
        session["username"] = username

        if role == "driver":
            return redirect(url_for("driver"))
        return redirect(url_for("police"))

    return render_template(
        "login.html",
        error="Invalid role, username, or password."
    ), 401


@app.route("/driver")
@require_role("driver")
def driver():
    return render_template(
        "driver.html",
        username=session.get("username", "Driver"),
        **snapshot()
    )


@app.route("/police")
@require_role("police")
def police():
    return render_template(
        "police.html",
        username=session.get("username", "Police Officer"),
        **snapshot()
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/dashboard")
def dashboard_api():
    return jsonify(snapshot())


# ESP8266 can POST GPS data here.
# Example JSON: {"latitude":11.01,"longitude":76.95,
# "speed":35,"direction":"EAST","emergency":true}
@app.route("/gps", methods=["POST"])
def update_gps():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(success=False, message="Send valid JSON."), 400

    updates = {}

    try:
        if "latitude" in data:
            value = float(data["latitude"])
            if not -90 <= value <= 90:
                raise ValueError("Latitude must be between -90 and 90.")
            updates["latitude"] = value

        if "longitude" in data:
            value = float(data["longitude"])
            if not -180 <= value <= 180:
                raise ValueError("Longitude must be between -180 and 180.")
            updates["longitude"] = value

        if "speed" in data:
            value = float(data["speed"])
            if value < 0:
                raise ValueError("Speed cannot be negative.")
            updates["speed"] = value

        if "distance_km" in data:
            value = float(data["distance_km"])
            if value < 0:
                raise ValueError("Distance cannot be negative.")
            updates["distance_km"] = value

        if "direction" in data:
            direction = str(data["direction"]).upper().strip()
            if direction not in DIRECTIONS:
                raise ValueError("Direction must be NORTH, SOUTH, EAST, or WEST.")
            updates["direction"] = direction

        if "emergency" in data:
            value = data["emergency"]
            if isinstance(value, bool):
                updates["emergency"] = value
            elif str(value).lower() in ("true", "1", "yes"):
                updates["emergency"] = True
            elif str(value).lower() in ("false", "0", "no"):
                updates["emergency"] = False
            else:
                raise ValueError("Emergency must be true or false.")

        for key in ("ambulance_id", "junction"):
            if key in data:
                updates[key] = str(data[key]).strip()[:100]

    except (ValueError, TypeError) as error:
        return jsonify(success=False, message=str(error)), 400

    with lock:
        ambulance.update(updates)
        ambulance["last_updated"] = datetime.now(timezone.utc).isoformat()

        direction = ambulance["direction"]
        ambulance["signal"] = signals[direction]

    return jsonify(success=True, data=snapshot())


# Police-only dashboard control.
# This changes the web application's signal state, not FPGA hardware directly.
@app.route("/traffic-signals", methods=["POST"])
@require_role("police")
def update_signals():
    data = request.get_json(silent=True) or {}
    direction = str(data.get("direction", "")).upper().strip()

    if direction not in DIRECTIONS:
        return jsonify(success=False, message="Invalid direction."), 400

    with lock:
        for road in signals:
            signals[road] = "RED"

        signals[direction] = "GREEN"
        ambulance["direction"] = direction
        ambulance["signal"] = "GREEN"
        ambulance["last_updated"] = datetime.now(timezone.utc).isoformat()

    return jsonify(
        success=True,
        message=f"{direction} selected for dashboard demo.",
        signals=dict(signals)
    )


@app.route("/priority/reset", methods=["POST"])
@require_role("police")
def reset_priority():
    with lock:
        for road in signals:
            signals[road] = "RED"

        ambulance["signal"] = "RED"
        ambulance["last_updated"] = datetime.now(timezone.utc).isoformat()

    return jsonify(success=True, message="Demo signals reset.")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
