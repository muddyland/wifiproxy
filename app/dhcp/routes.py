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
