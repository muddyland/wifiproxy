from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from app.system import bp
from app.system import utils
from app.validators import (
    ValidationError, validate_hostname, validate_service_name,
    validate_ip, validate_domain, validate_dns_record_type,
)


@bp.route("/")
@login_required
def index():
    info = utils.get_full_info()
    host_dns1, host_dns2 = utils.get_host_dns()
    return render_template("system/index.html", info=info,
                           host_dns1=host_dns1, host_dns2=host_dns2)


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
    try:
        lines = min(int(request.args.get("lines", 100)), 500)
    except (ValueError, TypeError):
        lines = 100
    try:
        unit = validate_service_name(request.args.get("unit", ""))
    except ValidationError:
        unit = ""
    return jsonify({"logs": utils.get_logs(lines, unit)})


@bp.route("/host-dns", methods=["POST"])
@login_required
def save_host_dns():
    from app.models import DhcpConfig
    from app import db
    from app.dhcp import utils as dhcp_utils
    try:
        dns1 = validate_ip(request.form.get("dns1", ""), "Primary DNS")
        dns2_raw = request.form.get("dns2", "").strip()
        dns2 = validate_ip(dns2_raw, "Secondary DNS") if dns2_raw else ""
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("system.index"))

    ok, msg = utils.set_host_dns(dns1, dns2)
    flash(msg, "success" if ok else "danger")

    if ok:
        cfg = DhcpConfig.query.first()
        if cfg:
            cfg.dns1 = dns1
            if dns2:
                cfg.dns2 = dns2
            db.session.commit()
            dhcp_utils.write_dnsmasq_config(cfg)

    return redirect(url_for("system.index"))


@bp.route("/dns-lookup")
@login_required
def dns_lookup():
    domain = request.args.get("domain", "").strip()
    record_type = request.args.get("type", "A").strip() or "A"
    server = request.args.get("server", "").strip()

    if not domain:
        return jsonify({"error": "Domain is required."}), 400

    try:
        domain = validate_domain(domain)
        record_type = validate_dns_record_type(record_type)
        if server:
            try:
                validate_ip(server, "DNS server")
            except ValidationError:
                server = validate_hostname(server)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400

    result = utils.dig_lookup(domain, record_type, server)
    return jsonify(result)


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
