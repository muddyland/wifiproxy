from flask import Blueprint
bp = Blueprint("wireguard", __name__)
from app.wireguard import routes  # noqa: E402, F401
