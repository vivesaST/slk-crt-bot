"""Flask app — multi-strategy dashboard"""
from flask import Flask, render_template, jsonify, request
import config
from bot_runner import runner
from modules.alerter import test_alert_slk, test_alert_daily_crt, test_alert_h4_crt

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(runner.status())


@app.route("/api/activities")
def api_activities():
    return jsonify(runner.get_activities(request.args.get("limit", 50, type=int)))


@app.route("/api/start", methods=["POST"])
def api_start():
    if runner.is_running:
        return jsonify({"success": False, "message": "Already running"})
    ok = runner.start()
    return jsonify({"success": ok, "message": "Bot started" if ok else "Failed"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not runner.is_running:
        return jsonify({"success": False, "message": "Not running"})
    ok = runner.stop()
    return jsonify({"success": ok, "message": "Bot stopped" if ok else "Failed"})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(runner.settings)
    data = request.get_json(force=True, silent=True) or {}
    runner.update_settings(
        slk=data.get("slk"),
        daily_crt=data.get("daily_crt"),
        h4_crt=data.get("h4_crt"),
    )
    return jsonify({"success": True, "settings": runner.settings})


@app.route("/api/test/<strategy>", methods=["POST"])
def api_test(strategy):
    strategy = strategy.lower()
    if strategy == "slk":
        ok = test_alert_slk()
    elif strategy in ("daily_crt", "daily"):
        ok = test_alert_daily_crt()
    elif strategy in ("h4_crt", "h4"):
        ok = test_alert_h4_crt()
    else:
        return jsonify({"success": False, "message": "Unknown strategy"})
    return jsonify({
        "success": ok,
        "message": f"Test {strategy} sent" if ok else f"Test {strategy} failed",
    })


if __name__ == "__main__":
    port = int(__import__("os").environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
