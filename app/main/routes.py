import psutil
from flask import render_template, jsonify
from flask_login import login_required
from app.main import bp
from app.wifi import utils as wifi_utils
from app.dhcp import utils as dhcp_utils
from app.tailscale import utils as ts_utils
from app.system import utils as sys_utils
from app.models import WifiNetwork


@bp.route("/")
@login_required
def dashboard():
    wifi = wifi_utils.get_current_connection()
    if wifi["connected"]:
        active_net = WifiNetwork.query.filter_by(ssid=wifi["ssid"]).first()
        wifi["priority"] = active_net.priority if active_net else None
    ctx = {
        "wifi": wifi,
        "bridge": dhcp_utils.get_bridge_status(),
        "tailscale": ts_utils.get_status(),
        "system": sys_utils.get_full_info(),
    }
    return render_template("dashboard.html", **ctx)


@bp.route("/api/stats")
@login_required
def api_stats():
    return jsonify(sys_utils.get_full_info())


@bp.route("/api/logs")
@login_required
def api_logs():
    return jsonify({"logs": sys_utils.get_logs(lines=30, unit="wifiproxy")})


@bp.route("/api/traffic")
@login_required
def api_traffic():
    counters = psutil.net_io_counters(pernic=True)
    result = {}
    for iface in ["wlan0", "eth0"]:
        c = counters.get(iface)
        if c:
            result[iface] = {"rx": c.bytes_recv, "tx": c.bytes_sent}
    return jsonify(result)


@bp.route("/api/services")
@login_required
def api_services():
    return jsonify(sys_utils.get_service_statuses())


@bp.route("/api/leases")
@login_required
def api_leases():
    return jsonify(dhcp_utils.get_leases())
