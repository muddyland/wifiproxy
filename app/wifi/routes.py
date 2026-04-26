from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from app.wifi import bp
from app.wifi import utils
from app.models import WifiNetwork
from app import db
from app.validators import (ValidationError, validate_ssid, validate_bssid,
                             validate_priority)


@bp.route("/")
@login_required
def index():
    networks = WifiNetwork.query.order_by(WifiNetwork.priority.desc()).all()
    current = utils.get_current_connection()
    if current["connected"]:
        active_net = WifiNetwork.query.filter_by(ssid=current["ssid"]).first()
        current["priority"] = active_net.priority if active_net else None
    db_ssids = {n.ssid for n in networks}
    nm_only = utils.get_nm_only_connections(db_ssids)
    return render_template("wifi/index.html", networks=networks, current=current,
                           nm_only=nm_only)


@bp.route("/scan")
@login_required
def scan():
    results = utils.scan_networks()
    return jsonify(results)


@bp.route("/add", methods=["POST"])
@login_required
def add():
    try:
        ssid = validate_ssid(request.form.get("ssid", ""))
        priority = validate_priority(request.form.get("priority", 10))
        raw_bssid = request.form.get("bssid", "").strip()
        bssid = validate_bssid(raw_bssid) if raw_bssid else None
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("wifi.index"))

    password = request.form.get("password", "")
    if len(password) > 128:
        flash("Password too long.", "danger")
        return redirect(url_for("wifi.index"))

    hidden = bool(request.form.get("hidden"))
    connect_now = bool(request.form.get("connect_now"))

    existing = WifiNetwork.query.filter_by(ssid=ssid).first()
    if existing:
        existing.password = password
        existing.priority = priority
        existing.hidden = hidden
        existing.bssid = bssid
        existing.auto_connect = True
        flash(f"Updated network: {ssid}", "info")
    else:
        net = WifiNetwork(ssid=ssid, priority=priority, hidden=hidden, bssid=bssid)
        net.password = password
        db.session.add(net)
        flash(f"Saved network: {ssid}", "success")

    db.session.commit()
    utils.set_nm_priority(ssid, priority)

    if connect_now:
        ok, msg = utils.connect(ssid, password, bssid)
        flash(msg, "success" if ok else "danger")

    return redirect(url_for("wifi.index"))


@bp.route("/import-nm", methods=["POST"])
@login_required
def import_nm():
    """Import a NetworkManager WiFi connection into the app DB."""
    try:
        ssid = validate_ssid(request.form.get("ssid", ""))
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("wifi.index"))

    if not WifiNetwork.query.filter_by(ssid=ssid).first():
        net = WifiNetwork(ssid=ssid, priority=10)
        db.session.add(net)
        db.session.commit()
        utils.set_nm_priority(ssid, 10)
        flash(f"Imported '{ssid}' from NetworkManager.", "success")
    return redirect(url_for("wifi.index"))


@bp.route("/connect/<int:network_id>", methods=["POST"])
@login_required
def connect(network_id):
    net = db.get_or_404(WifiNetwork, network_id)
    ok, msg = utils.connect(net.ssid, net.password, net.bssid)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("wifi.index"))


@bp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    ok, msg = utils.disconnect()
    flash(msg or "Disconnected.", "info" if ok else "danger")
    return redirect(url_for("wifi.index"))


@bp.route("/delete/<int:network_id>", methods=["POST"])
@login_required
def delete(network_id):
    net = db.get_or_404(WifiNetwork, network_id)
    utils.forget_network(net.ssid)
    db.session.delete(net)
    db.session.commit()
    flash(f"Removed network: {net.ssid}", "info")
    return redirect(url_for("wifi.index"))


@bp.route("/priority", methods=["POST"])
@login_required
def update_priorities():
    data = request.get_json(silent=True) or {}
    ids = data.get("order", [])
    if not isinstance(ids, list):
        return jsonify({"ok": False, "error": "Invalid payload"}), 400

    total = len(ids)
    for i, nid in enumerate(ids):
        if not isinstance(nid, int):
            continue
        net = db.session.get(WifiNetwork, nid)
        if net:
            net.priority = (total - i) * 10
            utils.set_nm_priority(net.ssid, net.priority)
    db.session.commit()
    return jsonify({"ok": True})
