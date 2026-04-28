import json
import io
import pytest
from app.models import User, WifiNetwork, DhcpConfig, TailscaleConfig, DhcpReservation
from app import db
from app.backup.utils import is_fresh_install, export_backup, import_backup


class TestFreshInstallDetection:
    def test_fresh_install_true_with_default_password(self, app):
        with app.app_context():
            assert is_fresh_install() is True

    def test_fresh_install_false_after_password_change(self, app):
        with app.app_context():
            u = User.query.filter_by(username="admin").first()
            u.set_password("securepass1")
            db.session.commit()
            assert is_fresh_install() is False


class TestSetupRoute:
    def test_setup_renders_on_fresh_install(self, client):
        r = client.get("/setup")
        assert r.status_code == 200
        assert b"Fresh install" in r.data

    def test_setup_redirects_when_not_fresh(self, client, app):
        with app.app_context():
            u = User.query.filter_by(username="admin").first()
            u.set_password("securepass1")
            db.session.commit()
        r = client.get("/setup")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_setup_sets_password(self, client, app):
        r = client.post("/setup", data={
            "new_password": "mynewpassword",
            "confirm_password": "mynewpassword",
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b"Setup complete" in r.data
        with app.app_context():
            u = User.query.filter_by(username="admin").first()
            assert u.check_password("mynewpassword")

    def test_setup_rejects_short_password(self, client):
        r = client.post("/setup", data={
            "new_password": "short",
            "confirm_password": "short",
        }, follow_redirects=True)
        assert b"at least 8 characters" in r.data

    def test_setup_rejects_mismatched_passwords(self, client):
        r = client.post("/setup", data={
            "new_password": "password1one",
            "confirm_password": "password2two",
        }, follow_redirects=True)
        assert b"do not match" in r.data

    def test_setup_with_backup_file(self, client, app):
        backup = {
            "version": "1",
            "created_at": "2025-01-01T00:00:00+00:00",
            "hostname": "test-host",
            "data": {
                "dhcp_config": {
                    "lan_interface": "eth0", "wan_interface": "wlan0",
                    "gateway": "10.0.0.1", "subnet_mask": "255.255.255.0",
                    "dns1": "1.1.1.1", "dns2": "1.0.0.1",
                    "range_start": "10.0.0.100", "range_end": "10.0.0.200",
                    "lease_time": "12h",
                },
                "dhcp_reservations": [],
                "wifi_networks": [
                    {"ssid": "HomeNet", "password": "secret", "priority": 5,
                     "bssid": None, "auto_connect": True, "hidden": False}
                ],
                "tailscale_config": {},
                "wireguard_tunnels": [],
            },
        }
        data = {
            "new_password": "mynewpassword",
            "confirm_password": "mynewpassword",
            "backup_file": (io.BytesIO(json.dumps(backup).encode()), "backup.json"),
        }
        r = client.post("/setup", data=data, content_type="multipart/form-data",
                        follow_redirects=True)
        assert r.status_code == 200
        assert b"Setup complete" in r.data
        with app.app_context():
            nets = WifiNetwork.query.all()
            assert len(nets) == 1
            assert nets[0].ssid == "HomeNet"
            cfg = DhcpConfig.query.first()
            assert cfg.gateway == "10.0.0.1"

    def test_setup_rejects_invalid_json(self, client):
        data = {
            "new_password": "mynewpassword",
            "confirm_password": "mynewpassword",
            "backup_file": (io.BytesIO(b"not valid json at all"), "backup.json"),
        }
        r = client.post("/setup", data=data, content_type="multipart/form-data",
                        follow_redirects=True)
        assert b"Invalid backup file" in r.data

    def test_login_redirects_to_setup_on_fresh_install(self, client):
        r = client.get("/login")
        assert r.status_code == 302
        assert "/setup" in r.headers["Location"]


class TestBackupRoutes:
    def test_backup_index_requires_login(self, client):
        r = client.get("/backup")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_backup_index_renders(self, auth_client):
        r = auth_client.get("/backup")
        assert r.status_code == 200
        assert b"Create Backup" in r.data
        assert b"Restore" in r.data

    def test_backup_create_downloads_json(self, auth_client):
        r = auth_client.post("/backup/create")
        assert r.status_code == 200
        assert r.content_type == "application/json"
        assert b"attachment" in r.headers["Content-Disposition"].encode()
        payload = json.loads(r.data)
        assert payload["version"] == "1"
        assert "data" in payload
        assert "dhcp_config" in payload["data"]

    def test_backup_create_includes_wifi_networks(self, auth_client, app):
        with app.app_context():
            n = WifiNetwork(ssid="BackupNet", priority=10)
            n.password = "wifipass"
            db.session.add(n)
            db.session.commit()
        r = auth_client.post("/backup/create")
        payload = json.loads(r.data)
        nets = payload["data"]["wifi_networks"]
        assert any(n["ssid"] == "BackupNet" and n["password"] == "wifipass" for n in nets)

    def test_backup_restore_replaces_data(self, auth_client, app):
        with app.app_context():
            n = WifiNetwork(ssid="OldNet", priority=10)
            db.session.add(n)
            db.session.commit()

        backup = {
            "version": "1",
            "created_at": "2025-01-01T00:00:00+00:00",
            "hostname": "",
            "data": {
                "dhcp_config": {
                    "lan_interface": "eth0", "wan_interface": "wlan0",
                    "gateway": "172.16.0.1", "subnet_mask": "255.255.0.0",
                    "dns1": "8.8.8.8", "dns2": "8.8.4.4",
                    "range_start": "172.16.0.100", "range_end": "172.16.0.200",
                    "lease_time": "24h",
                },
                "dhcp_reservations": [
                    {"mac": "aa:bb:cc:dd:ee:ff", "nickname": "Desktop", "static_ip": "172.16.0.10"}
                ],
                "wifi_networks": [
                    {"ssid": "NewNet", "password": "newpass", "priority": 20,
                     "bssid": None, "auto_connect": True, "hidden": False}
                ],
                "tailscale_config": {
                    "login_server": "https://controlplane.tailscale.com",
                    "auth_key": "", "advertise_exit_node": False,
                    "accept_routes": False, "accept_dns": True, "advertise_routes": "",
                },
                "wireguard_tunnels": [],
            },
        }
        data = {
            "backup_file": (io.BytesIO(json.dumps(backup).encode()), "backup.json"),
        }
        r = auth_client.post("/backup/restore", data=data, content_type="multipart/form-data",
                             follow_redirects=True)
        assert b"Backup restored" in r.data
        with app.app_context():
            nets = WifiNetwork.query.all()
            assert len(nets) == 1
            assert nets[0].ssid == "NewNet"
            reservations = DhcpReservation.query.all()
            assert len(reservations) == 1
            assert reservations[0].nickname == "Desktop"
            cfg = DhcpConfig.query.first()
            assert cfg.gateway == "172.16.0.1"

    def test_backup_restore_rejects_missing_file(self, auth_client):
        r = auth_client.post("/backup/restore", data={}, follow_redirects=True)
        assert b"No backup file" in r.data

    def test_backup_restore_rejects_invalid_json(self, auth_client):
        data = {
            "backup_file": (io.BytesIO(b"{ bad json }"), "backup.json"),
        }
        r = auth_client.post("/backup/restore", data=data, content_type="multipart/form-data",
                             follow_redirects=True)
        assert b"Invalid backup file" in r.data

    def test_backup_restore_rejects_wrong_version(self, auth_client):
        backup = {"version": "99", "data": {}}
        data = {
            "backup_file": (io.BytesIO(json.dumps(backup).encode()), "backup.json"),
        }
        r = auth_client.post("/backup/restore", data=data, content_type="multipart/form-data",
                             follow_redirects=True)
        assert b"Unsupported backup version" in r.data


class TestExportImportRoundtrip:
    def test_roundtrip_wifi_passwords(self, app):
        with app.app_context():
            n = WifiNetwork(ssid="RoundtripNet", priority=5)
            n.password = "supersecret"
            db.session.add(n)
            db.session.commit()

            data = export_backup()
            WifiNetwork.query.delete()
            db.session.commit()

            ok, _ = import_backup(data)
            assert ok
            nets = WifiNetwork.query.all()
            assert len(nets) == 1
            assert nets[0].ssid == "RoundtripNet"
            assert nets[0].password == "supersecret"

    def test_import_skips_invalid_tunnel_name(self, app):
        backup = {
            "version": "1",
            "data": {
                "wireguard_tunnels": [
                    {"name": "bad name!", "config": "[Interface]\nPrivateKey=test"}
                ],
            },
        }
        with app.app_context():
            ok, msg = import_backup(backup)
            assert ok
            assert "bad name!" in msg
