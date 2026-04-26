from flask import Blueprint

bp = Blueprint("tailscale", __name__)

from app.tailscale import routes  # noqa: E402, F401
