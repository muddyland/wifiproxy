from flask import render_template, jsonify
from flask_login import login_required
from app.main import bp
from app.wifi import utils as wifi_utils
from app.dhcp import utils as dhcp_utils
from app.tailscale import utils as ts_utils
from app.system import utils as sys_utils


@bp.route("/")
@login_required
def dashboard():
    ctx = {
        "wifi": wifi_utils.get_current_connection(),
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
