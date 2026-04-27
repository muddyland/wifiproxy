from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from app.crypto import encrypt, decrypt


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class WifiNetwork(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ssid = db.Column(db.String(256), nullable=False)
    _password = db.Column("password", db.Text)
    priority = db.Column(db.Integer, default=10)
    bssid = db.Column(db.String(17))
    auto_connect = db.Column(db.Boolean, default=True)
    hidden = db.Column(db.Boolean, default=False)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def password(self):
        return decrypt(self._password) if self._password else ""

    @password.setter
    def password(self, value):
        self._password = encrypt(value) if value else None


class DhcpConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lan_interface = db.Column(db.String(20), default="eth0")
    wan_interface = db.Column(db.String(20), default="wlan0")
    gateway = db.Column(db.String(18), default="192.168.50.1")
    subnet_mask = db.Column(db.String(18), default="255.255.255.0")
    dns1 = db.Column(db.String(18), default="8.8.8.8")
    dns2 = db.Column(db.String(18), default="8.8.4.4")
    range_start = db.Column(db.String(18), default="192.168.50.100")
    range_end = db.Column(db.String(18), default="192.168.50.200")
    lease_time = db.Column(db.String(10), default="24h")


class TailscaleConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login_server = db.Column(db.String(256), default="https://controlplane.tailscale.com")
    _auth_key = db.Column("auth_key", db.Text)
    advertise_exit_node = db.Column(db.Boolean, default=False)
    accept_routes = db.Column(db.Boolean, default=False)
    accept_dns = db.Column(db.Boolean, default=True)
    advertise_routes = db.Column(db.String(512), default="")

    @property
    def auth_key(self):
        return decrypt(self._auth_key) if self._auth_key else ""

    @auth_key.setter
    def auth_key(self, value):
        self._auth_key = encrypt(value) if value else None


class DhcpReservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mac = db.Column(db.String(17), unique=True, nullable=False)
    nickname = db.Column(db.String(64), default="")
    static_ip = db.Column(db.String(15), default="")
