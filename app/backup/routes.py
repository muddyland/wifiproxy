import json
from datetime import datetime, timezone
from flask import render_template, redirect, url_for, flash, request, Response, current_app
from flask_login import login_required
from app.backup import bp
from app.backup.utils import export_backup, import_backup, is_fresh_install
from app.models import User
from app import db, limiter


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if not is_fresh_install():
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        backup_file = request.files.get("backup_file")

        if len(new_pw) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("backup/setup.html")
        if new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
            return render_template("backup/setup.html")

        if backup_file and backup_file.filename:
            try:
                data = json.loads(backup_file.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                flash("Invalid backup file — must be a JSON file exported from this app.", "danger")
                return render_template("backup/setup.html")
            ok, msg = import_backup(data)
            if not ok:
                flash(msg, "danger")
                return render_template("backup/setup.html")
            flash(msg, "success")

        user = User.query.filter_by(username="admin").first()
        user.set_password(new_pw)
        db.session.commit()
        flash("Setup complete. Please sign in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("backup/setup.html")


@bp.route("/backup")
@login_required
def index():
    return render_template("backup/index.html")


@bp.route("/backup/create", methods=["POST"])
@login_required
def create():
    try:
        data = export_backup()
        json_str = json.dumps(data, indent=2)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"wifiproxy_backup_{timestamp}.json"
        return Response(
            json_str,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        current_app.logger.error("Backup create failed: %s", exc)
        flash(f"Backup failed: {exc}", "danger")
        return redirect(url_for("backup.index"))


@bp.route("/backup/restore", methods=["POST"])
@login_required
@limiter.limit("5 per hour")
def restore():
    backup_file = request.files.get("backup_file")
    if not backup_file or not backup_file.filename:
        flash("No backup file selected.", "danger")
        return redirect(url_for("backup.index"))

    try:
        data = json.loads(backup_file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("Invalid backup file — must be a JSON file exported from this app.", "danger")
        return redirect(url_for("backup.index"))

    ok, msg = import_backup(data)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("backup.index"))
