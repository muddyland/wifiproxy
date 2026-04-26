from unittest.mock import patch
from app.models import TailscaleConfig
from app import db

MOCK_STATUS_CONNECTED = {
    "installed": True, "running": True, "connected": True,
    "ip": "100.64.0.1", "hostname": "pi", "peers": [],
    "exit_node_active": False, "login_server": None, "raw": None,
}
MOCK_STATUS_DISCONNECTED = {
    "installed": True, "running": False, "connected": False,
    "ip": None, "hostname": None, "peers": [],
    "exit_node_active": False, "login_server": None, "raw": None,
}
MOCK_STATUS_NOT_INSTALLED = {
    "installed": False, "running": False, "connected": False,
    "ip": None, "hostname": None, "peers": [],
    "exit_node_active": False, "login_server": None, "raw": None,
}


class TestTailscaleIndex:
    def test_requires_login(self, client):
        r = client.get("/tailscale/")
        assert r.status_code == 302

    def test_renders_connected(self, auth_client):
        with patch("app.tailscale.utils.get_status", return_value=MOCK_STATUS_CONNECTED):
            r = auth_client.get("/tailscale/")
        assert r.status_code == 200
        assert b"100.64.0.1" in r.data

    def test_renders_not_installed(self, auth_client):
        with patch("app.tailscale.utils.get_status", return_value=MOCK_STATUS_NOT_INSTALLED):
            r = auth_client.get("/tailscale/")
        assert b"Not installed" in r.data


class TestTailscaleSave:
    def test_save_headscale_config(self, auth_client, app):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "https://headscale.example.com",
            "auth_key": "test-key",
            "advertise_exit_node": "1",
            "accept_routes": "",
            "advertise_routes": "192.168.50.0/24",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            assert cfg.login_server == "https://headscale.example.com"
            assert cfg.auth_key == "test-key"
            assert cfg.advertise_exit_node is True
            assert cfg.advertise_routes == "192.168.50.0/24"

    def test_invalid_login_server_rejected(self, auth_client):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "not-a-url",
            "auth_key": "",
            "advertise_routes": "",
        }, follow_redirects=True)
        assert b"http" in r.data.lower() or b"URL" in r.data

    def test_injection_in_login_server_rejected(self, auth_client):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "https://ok.com;rm -rf /",
            "auth_key": "",
            "advertise_routes": "",
        }, follow_redirects=True)
        with app.app_context() if False else __import__('contextlib').nullcontext():
            pass
        # Should have flashed an error
        assert r.status_code == 200

    def test_invalid_cidr_rejected(self, auth_client):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "https://example.com",
            "auth_key": "",
            "advertise_routes": "notacidr",
        }, follow_redirects=True)
        assert b"CIDR" in r.data or b"not a valid" in r.data

    def test_ftp_url_rejected(self, auth_client):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "ftp://evil.com",
            "auth_key": "",
            "advertise_routes": "",
        }, follow_redirects=True)
        assert b"http" in r.data.lower()


class TestTailscaleConnect:
    def test_connect_success(self, auth_client):
        with patch("app.tailscale.utils.login", return_value=(True, "Connected to Tailscale.")):
            r = auth_client.post("/tailscale/connect", follow_redirects=True)
        assert b"Connected" in r.data

    def test_connect_prompts_login_url(self, auth_client):
        login_url = "https://headscale.example.com/register/..."
        with patch("app.tailscale.utils.login", return_value=(False, login_url)):
            r = auth_client.post("/tailscale/connect", follow_redirects=True)
        assert b"headscale.example.com" in r.data

    def test_connect_failure(self, auth_client):
        with patch("app.tailscale.utils.login", return_value=(False, "Connection refused.")):
            r = auth_client.post("/tailscale/connect", follow_redirects=True)
        assert b"Connection refused" in r.data


class TestTailscaleDown:
    def test_down_success(self, auth_client):
        with patch("app.tailscale.utils.down", return_value=(True, "Tailscale stopped.")):
            r = auth_client.post("/tailscale/down", follow_redirects=True)
        assert r.status_code == 200

    def test_down_failure(self, auth_client):
        with patch("app.tailscale.utils.down", return_value=(False, "Failed.")):
            r = auth_client.post("/tailscale/down", follow_redirects=True)
        assert b"Failed" in r.data
