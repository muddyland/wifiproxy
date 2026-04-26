from flask import Blueprint

bp = Blueprint("dhcp", __name__)

from app.dhcp import routes  # noqa: E402, F401
