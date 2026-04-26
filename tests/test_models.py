import pytest
from app.models import User, WifiNetwork, DhcpConfig, TailscaleConfig
from app import db


class TestUser:
    def test_password_hashing(self, app):
        with app.app_context():
            u = User(username="testuser")
            u.set_password("mysecretpassword")
            assert u.password_hash != "mysecretpassword"
            assert u.check_password("mysecretpassword")
            assert not u.check_password("wrongpassword")

    def test_password_hash_is_not_plaintext(self, app):
        with app.app_context():
            u = User(username="testuser")
            u.set_password("hunter2")
            assert "hunter2" not in u.password_hash

    def test_different_passwords_different_hashes(self, app):
        with app.app_context():
            u1 = User(username="a")
            u2 = User(username="b")
            u1.set_password("samepassword")
            u2.set_password("samepassword")
            # bcrypt/PBKDF2 generates different salts each time
            assert u1.password_hash != u2.password_hash


class TestWifiNetwork:
    def test_password_encryption(self, app):
        with app.app_context():
            net = WifiNetwork(ssid="TestNet")
            net.password = "supersecret"
            db.session.add(net)
            db.session.commit()

            fetched = WifiNetwork.query.filter_by(ssid="TestNet").first()
            # Raw column should not contain plaintext
            assert fetched._password != "supersecret"
            # Property should decrypt correctly
            assert fetched.password == "supersecret"

    def test_empty_password(self, app):
        with app.app_context():
            net = WifiNetwork(ssid="OpenNet")
            net.password = ""
            db.session.add(net)
            db.session.commit()

            fetched = WifiNetwork.query.filter_by(ssid="OpenNet").first()
            assert fetched.password == ""
            assert fetched._password is None

    def test_default_priority(self, app):
        with app.app_context():
            net = WifiNetwork(ssid="Net")
            net.password = ""
            db.session.add(net)
            db.session.commit()
            assert net.priority == 10

    def test_default_auto_connect(self, app):
        with app.app_context():
            net = WifiNetwork(ssid="Net2")
            net.password = ""
            db.session.add(net)
            db.session.commit()
            assert net.auto_connect is True


class TestDhcpConfig:
    def test_defaults(self, app):
        with app.app_context():
            cfg = DhcpConfig.query.first()
            assert cfg is not None
            assert cfg.gateway == "192.168.50.1"
            assert cfg.range_start == "192.168.50.100"
            assert cfg.range_end == "192.168.50.200"
            assert cfg.dns1 == "8.8.8.8"
            assert cfg.lease_time == "24h"


class TestTailscaleConfig:
    def test_defaults(self, app):
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            assert cfg is not None
            assert "tailscale.com" in cfg.login_server

    def test_auth_key_encryption(self, app):
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            cfg.auth_key = "tskey-auth-secret123"
            db.session.commit()

            fetched = TailscaleConfig.query.first()
            assert fetched._auth_key != "tskey-auth-secret123"
            assert fetched.auth_key == "tskey-auth-secret123"

    def test_empty_auth_key(self, app):
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            cfg.auth_key = ""
            db.session.commit()

            fetched = TailscaleConfig.query.first()
            assert fetched.auth_key == ""
            assert fetched._auth_key is None
