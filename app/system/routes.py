from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from app.system import bp
from app.system import utils
from app.validators import ValidationError, validate_hostname


@bp.route("/")
@login_required
def index():
    info = utils.get_full_info()
    return render_template("system/index.html", info=info)


@bp.route("/hostname", methods=["POST"])
@login_required
def set_hostname():
    try:
        name = validate_hostname(request.form.get("hostname", ""))
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("system.index"))
    ok, msg = utils.set_hostname(name)
    flash(msg or "Hostname updated.", "success" if ok else "danger")
    return redirect(url_for("system.index"))


@bp.route("/update", methods=["POST"])
@login_required
def update():
    ok, msg = utils.run_update()
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("system.index"))


@bp.route("/check-updates")
@login_required
def check_updates():
    return jsonify({"message": utils.check_updates()})


@bp.route("/logs")
@login_required
def logs():
    lines = min(int(request.args.get("lines", 100)), 500)
    unit = request.args.get("unit", "")
    return jsonify({"logs": utils.get_logs(lines, unit)})


@bp.route("/reboot", methods=["POST"])
@login_required
def reboot():
    ok, msg = utils.reboot()
    flash(msg, "info" if ok else "danger")
    return redirect(url_for("system.index"))


@bp.route("/shutdown", methods=["POST"])
@login_required
def shutdown():
    ok, msg = utils.shutdown()
    flash(msg, "info" if ok else "danger")
    return redirect(url_for("system.index"))
