from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from app.wireguard import bp
from app.wireguard import utils
from app.validators import ValidationError, validate_tunnel_name


@bp.route("/")
@login_required
def index():
    tunnels = utils.get_tunnels()
    for t in tunnels:
        if t["active"]:
            t["stats"] = utils.get_stats(t["name"])
    return render_template("wireguard/index.html",
                           tunnels=tunnels,
                           installed=utils.is_installed())


@bp.route("/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("config")
    if not f or not f.filename:
        flash("No file selected.", "danger")
        return redirect(url_for("wireguard.index"))
    try:
        content = f.read().decode("utf-8")
    except Exception:
        flash("Could not read config file — must be UTF-8 text.", "danger")
        return redirect(url_for("wireguard.index"))
    if len(content) > 65536:
        flash("Config file too large (max 64 KB).", "danger")
        return redirect(url_for("wireguard.index"))
    try:
        name = validate_tunnel_name(request.form.get("name", ""))
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for("wireguard.index"))
    ok, msg = utils.save_config(name, content)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("wireguard.index"))


@bp.route("/connect/<name>", methods=["POST"])
@login_required
def connect(name):
    try:
        name = validate_tunnel_name(name)
    except ValidationError:
        flash("Invalid tunnel name.", "danger")
        return redirect(url_for("wireguard.index"))
    ok, msg = utils.connect(name)
    flash(msg or f"Connected {name}.", "success" if ok else "danger")
    return redirect(url_for("wireguard.index"))


@bp.route("/disconnect/<name>", methods=["POST"])
@login_required
def disconnect(name):
    try:
        name = validate_tunnel_name(name)
    except ValidationError:
        flash("Invalid tunnel name.", "danger")
        return redirect(url_for("wireguard.index"))
    ok, msg = utils.disconnect(name)
    flash(msg or f"Disconnected {name}.", "info" if ok else "danger")
    return redirect(url_for("wireguard.index"))


@bp.route("/autostart/<name>", methods=["POST"])
@login_required
def autostart(name):
    try:
        name = validate_tunnel_name(name)
    except ValidationError:
        flash("Invalid tunnel name.", "danger")
        return redirect(url_for("wireguard.index"))
    enable = request.form.get("enable") == "1"
    ok, msg = utils.set_autostart(name, enable)
    flash(msg or ("Autostart enabled." if enable else "Autostart disabled."),
          "success" if ok else "danger")
    return redirect(url_for("wireguard.index"))


@bp.route("/delete/<name>", methods=["POST"])
@login_required
def delete(name):
    try:
        name = validate_tunnel_name(name)
    except ValidationError:
        flash("Invalid tunnel name.", "danger")
        return redirect(url_for("wireguard.index"))
    ok, msg = utils.delete(name)
    flash(msg, "info" if ok else "danger")
    return redirect(url_for("wireguard.index"))


@bp.route("/stats/<name>")
@login_required
def stats(name):
    try:
        name = validate_tunnel_name(name)
    except ValidationError:
        return jsonify({"output": "Invalid tunnel name."})
    return jsonify({"output": utils.get_stats(name)})
