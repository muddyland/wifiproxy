from flask import Blueprint

bp = Blueprint("wifi", __name__)

from app.wifi import routes  # noqa: E402, F401
