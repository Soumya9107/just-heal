"""
app.py

Minimal Flask app that gives the self-healing scraper a visual home instead
of a terminal wall of text. Serves a dashboard showing:
  - current scraper health status
  - the latest extracted data
  - a history log of runs, breaks, and heals

Run with:
    python app.py
Then open http://localhost:5000 in your browser.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

app = Flask(__name__)

RUN_OUTPUT_FILE = "run_output.json"
HISTORY_FILE = "history.json"
COLLECTOR_ID_FILE = "collector_id.txt"


def load_json_safe(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig strips BOM if present
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def load_collector_id():
    if not os.path.exists(COLLECTOR_ID_FILE):
        return None
    with open(COLLECTOR_ID_FILE, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def status():
    """Returns current scraper state: latest data + history, for the dashboard to render."""
    run_output = load_json_safe(RUN_OUTPUT_FILE, [])
    history = load_json_safe(HISTORY_FILE, [])
    collector_id = load_collector_id()

    latest_record = run_output[0] if isinstance(run_output, list) and run_output else None
    latest_history_entry = history[-1] if history else None

    return jsonify({
        "collector_id": collector_id,
        "latest_record": latest_record,
        "latest_status": latest_history_entry,
        "history": history[-20:],  # most recent 20 runs
    })


@app.route("/api/run", methods=["POST"])
def trigger_run():
    """Triggers heal_loop.py as a subprocess and returns the outcome."""
    python_exe = sys.executable  # use the same interpreter (respects active venv)
    result = subprocess.run(
        [python_exe, "heal_loop.py"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return jsonify({
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)