from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_required
from app.tailscale import bp
from app.tailscale import utils
from app.models import TailscaleConfig
from app import db
from app.validators import ValidationError, validate_url, validate_cidr_list


@bp.route("/")
@login_required
def index():
    cfg = TailscaleConfig.query.first()
    status = utils.get_status()
    prefs = utils.get_prefs()
    login_url = session.pop("ts_login_url", None)
    return render_template("tailscale/index.html", cfg=cfg, status=status,
                           prefs=prefs, login_url=login_url)


@bp.route("/save", methods=["POST"])
@login_required
def save():
    cfg = TailscaleConfig.query.first()
    try:
        login_server = validate_url(request.form.get("login_server", ""), "Login server")
        routes_raw = request.form.get("advertise_routes", "").strip()
        advertise_routes = validate_cidr_list(routes_raw)
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("tailscale.index"))

    auth_key = request.form.get("auth_key", "").strip()
    if len(auth_key) > 256:
        flash("Auth key too long.", "danger")
        return redirect(url_for("tailscale.index"))

    cfg.login_server = login_server
    cfg.auth_key = auth_key
    cfg.advertise_exit_node = bool(request.form.get("advertise_exit_node"))
    cfg.accept_routes = bool(request.form.get("accept_routes"))
    cfg.accept_dns = bool(request.form.get("accept_dns"))
    cfg.advertise_routes = advertise_routes
    db.session.commit()
    flash("Tailscale configuration saved.", "success")
    return redirect(url_for("tailscale.index"))


@bp.route("/connect", methods=["POST"])
@login_required
def connect():
    cfg = TailscaleConfig.query.first()
    ok, msg = utils.login(
        login_server=cfg.login_server,
        auth_key=cfg.auth_key,
        advertise_exit_node=cfg.advertise_exit_node,
        accept_routes=cfg.accept_routes,
        advertise_routes=cfg.advertise_routes,
        accept_dns=getattr(cfg, "accept_dns", True),
    )
    if not ok and msg.startswith("https://"):
        session["ts_login_url"] = msg
        flash("Open the URL below to authenticate with your login server.", "info")
    elif ok:
        flash(msg, "success")
    else:
        flash(msg, "danger")
    return redirect(url_for("tailscale.index"))


@bp.route("/down", methods=["POST"])
@login_required
def bring_down():
    ok, msg = utils.down()
    flash(msg or "Tailscale brought down.", "info" if ok else "danger")
    return redirect(url_for("tailscale.index"))


@bp.route("/logout", methods=["POST"])
@login_required
def ts_logout():
    ok, msg = utils.logout()
    flash(msg or "Logged out of Tailscale.", "info" if ok else "danger")
    return redirect(url_for("tailscale.index"))


@bp.route("/exit-node/set", methods=["POST"])
@login_required
def set_exit_node():
    ip = request.form.get("ip", "").strip()
    if not ip:
        flash("No IP provided.", "danger")
        return redirect(url_for("tailscale.index"))
    ok, msg = utils.set_exit_node(ip)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("tailscale.index"))


@bp.route("/exit-node/clear", methods=["POST"])
@login_required
def clear_exit_node():
    ok, msg = utils.clear_exit_node()
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("tailscale.index"))
