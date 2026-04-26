from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required
from app.dhcp import bp
from app.dhcp import utils
from app.models import DhcpConfig
from app import db
from app.validators import (ValidationError, validate_ip, validate_interface,
                             validate_lease_time)



@bp.route("/")
@login_required
def index():
    cfg = DhcpConfig.query.first()
    bridge = utils.get_bridge_status()
    leases = utils.get_leases()
    return render_template("dhcp/index.html", cfg=cfg, bridge=bridge, leases=leases)


@bp.route("/save", methods=["POST"])
@login_required
def save():
    cfg = DhcpConfig.query.first()
    old_gateway = cfg.gateway

    try:
        cfg.lan_interface = validate_interface(
            request.form.get("lan_interface", ""), "LAN interface")
        cfg.wan_interface = validate_interface(
            request.form.get("wan_interface", ""), "WAN interface")
        cfg.gateway = validate_ip(request.form.get("gateway", ""), "Gateway")
        cfg.subnet_mask = validate_ip(request.form.get("subnet_mask", ""), "Subnet mask")
        cfg.dns1 = validate_ip(request.form.get("dns1", ""), "DNS 1")
        cfg.dns2 = validate_ip(request.form.get("dns2", ""), "DNS 2")
        cfg.range_start = validate_ip(request.form.get("range_start", ""), "Range start")
        cfg.range_end = validate_ip(request.form.get("range_end", ""), "Range end")
        cfg.lease_time = validate_lease_time(request.form.get("lease_time", ""))
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("dhcp.index"))

    db.session.commit()

    if cfg.gateway != old_gateway:
        nm_conn = current_app.config["NM_LAN_CONNECTION"]
        ok, msg = utils.update_lan_ip(nm_conn, cfg.gateway)
        if not ok:
            flash(f"Warning: could not update NM connection: {msg}", "warning")

    ok, msg = utils.write_dnsmasq_config(cfg)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("dhcp.index"))


@bp.route("/reapply-nat", methods=["POST"])
@login_required
def reapply_nat():
    cfg = DhcpConfig.query.first()
    ok, msg = utils.apply_iptables(cfg.wan_interface, cfg.lan_interface)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("dhcp.index"))


@bp.route("/leases")
@login_required
def leases_json():
    return jsonify(utils.get_leases())


@bp.route("/reservation/save", methods=["POST"])
@login_required
def save_reservation():
    from app.models import DhcpReservation
    mac = request.form.get("mac", "").strip().lower()
    nickname = request.form.get("nickname", "").strip()[:64]
    static_ip = request.form.get("static_ip", "").strip()
    if not mac:
        flash("MAC address required.", "danger")
        return redirect(url_for("dhcp.index"))
    res = DhcpReservation.query.filter_by(mac=mac).first()
    if not res:
        res = DhcpReservation(mac=mac)
        db.session.add(res)
    res.nickname = nickname
    res.static_ip = static_ip
    db.session.commit()
    cfg = DhcpConfig.query.first()
    utils.write_dnsmasq_config(cfg)
    flash("Reservation saved.", "success")
    return redirect(url_for("dhcp.index"))


@bp.route("/reservation/delete/<int:res_id>", methods=["POST"])
@login_required
def delete_reservation(res_id):
    from app.models import DhcpReservation
    res = db.get_or_404(DhcpReservation, res_id)
    db.session.delete(res)
    db.session.commit()
    cfg = DhcpConfig.query.first()
    utils.write_dnsmasq_config(cfg)
    flash("Reservation removed.", "info")
    return redirect(url_for("dhcp.index"))


@bp.route("/lease/invalidate", methods=["POST"])
@login_required
def invalidate_lease_route():
    ip = request.form.get("ip", "").strip()
    ok, msg = utils.invalidate_lease(ip)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("dhcp.index"))
