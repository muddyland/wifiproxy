from flask import Blueprint

bp = Blueprint("backup", __name__)

from app.backup import routes  # noqa: E402,F401
