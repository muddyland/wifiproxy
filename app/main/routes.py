from flask import render_template
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
        "system": sys_utils.get_quick_info(),
    }
    return render_template("dashboard.html", **ctx)
