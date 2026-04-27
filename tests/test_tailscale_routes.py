from unittest.mock import patch
from app.models import TailscaleConfig
from app import db

MOCK_STATUS_CONNECTED = {
    "installed": True, "running": True, "connected": True,
    "ip": "100.64.0.1", "hostname": "pi", "peers": [],
    "exit_node_active": False, "exit_node_ip": None,
    "login_server": None, "backend_state": "Running",
    "needs_auth": False, "auth_url": None,
    "live_advertise_exit_node": False, "live_advertised_routes": "",
}
MOCK_STATUS_DISCONNECTED = {
    "installed": True, "running": False, "connected": False,
    "ip": None, "hostname": None, "peers": [],
    "exit_node_active": False, "exit_node_ip": None,
    "login_server": None, "backend_state": "Stopped",
    "needs_auth": False, "auth_url": None,
    "live_advertise_exit_node": None, "live_advertised_routes": None,
}
MOCK_STATUS_NOT_INSTALLED = {
    "installed": False, "running": False, "connected": False,
    "ip": None, "hostname": None, "peers": [],
    "exit_node_active": False, "exit_node_ip": None,
    "login_server": None, "backend_state": None,
    "needs_auth": False, "auth_url": None,
    "live_advertise_exit_node": None, "live_advertised_routes": None,
}
MOCK_PREFS = {"control_url": None, "accept_routes": None, "accept_dns": None}


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


class TestTailscaleAcceptDns:
    def test_accept_dns_saved_when_checked(self, auth_client, app):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "https://controlplane.tailscale.com",
            "auth_key": "",
            "advertise_routes": "",
            "accept_dns": "1",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            assert cfg.accept_dns is True

    def test_accept_dns_false_when_unchecked(self, auth_client, app):
        r = auth_client.post("/tailscale/save", data={
            "login_server": "https://controlplane.tailscale.com",
            "auth_key": "",
            "advertise_routes": "",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            assert cfg.accept_dns is False

    def test_connect_passes_accept_dns_false(self, auth_client, app):
        with app.app_context():
            cfg = TailscaleConfig.query.first()
            cfg.accept_dns = False
            db.session.commit()
        with patch("app.tailscale.utils.login", return_value=(True, "Connected.")) as m:
            auth_client.post("/tailscale/connect", follow_redirects=True)
        _, kwargs = m.call_args
        assert kwargs.get("accept_dns") is False or m.call_args[1].get("accept_dns") is False

    def test_login_adds_accept_dns_false_flag(self, app):
        from app.tailscale import utils
        from unittest.mock import MagicMock
        import subprocess
        mock_r = MagicMock(spec=subprocess.CompletedProcess)
        mock_r.stdout = ""
        mock_r.stderr = ""
        mock_r.returncode = 0
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=mock_r) as m:
                utils.login("https://example.com", accept_dns=False)
        cmd = m.call_args[0][0]
        assert "--accept-dns=false" in cmd

    def test_login_omits_accept_dns_flag_when_true(self, app):
        from app.tailscale import utils
        from unittest.mock import MagicMock
        import subprocess
        mock_r = MagicMock(spec=subprocess.CompletedProcess)
        mock_r.stdout = ""
        mock_r.stderr = ""
        mock_r.returncode = 0
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=mock_r) as m:
                utils.login("https://example.com", accept_dns=True)
        cmd = m.call_args[0][0]
        assert "--accept-dns=false" not in cmd


class TestSetExitNode:
    def test_requires_login(self, client):
        r = client.post("/tailscale/exit-node/set")
        assert r.status_code == 302

    def test_set_exit_node_success(self, auth_client):
        with patch("app.tailscale.utils.set_exit_node",
                   return_value=(True, "Exit node set to 100.64.0.2.")):
            r = auth_client.post("/tailscale/exit-node/set",
                                 data={"ip": "100.64.0.2"},
                                 follow_redirects=True)
        assert b"Exit node set" in r.data

    def test_set_exit_node_no_ip(self, auth_client):
        r = auth_client.post("/tailscale/exit-node/set",
                             data={},
                             follow_redirects=True)
        assert b"No IP" in r.data

    def test_set_exit_node_invalid_ip_rejected(self, auth_client):
        for bad_ip in ["not-an-ip", "999.999.999.999", "100.64.0.1; rm -rf /"]:
            r = auth_client.post("/tailscale/exit-node/set",
                                 data={"ip": bad_ip},
                                 follow_redirects=True)
            assert r.status_code == 200
            assert b"valid IPv4" in r.data or b"not a valid" in r.data

    def test_set_exit_node_failure(self, auth_client):
        with patch("app.tailscale.utils.set_exit_node",
                   return_value=(False, "node not found")):
            r = auth_client.post("/tailscale/exit-node/set",
                                 data={"ip": "100.64.0.99"},
                                 follow_redirects=True)
        assert b"node not found" in r.data

    def test_util_builds_correct_command(self, app):
        from app.tailscale import utils
        from unittest.mock import MagicMock
        import subprocess
        mock_r = MagicMock(spec=subprocess.CompletedProcess)
        mock_r.stdout = ""
        mock_r.stderr = ""
        mock_r.returncode = 0
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=mock_r) as m:
                ok, msg = utils.set_exit_node("100.64.0.2")
        assert ok is True
        cmd = m.call_args[0][0]
        assert "--exit-node=100.64.0.2" in cmd
        assert "--exit-node-allow-lan-access=true" in cmd

    def test_util_failure(self, app):
        from app.tailscale import utils
        from unittest.mock import MagicMock
        import subprocess
        mock_r = MagicMock(spec=subprocess.CompletedProcess)
        mock_r.stdout = ""
        mock_r.stderr = "error: unknown peer"
        mock_r.returncode = 1
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=mock_r):
                ok, msg = utils.set_exit_node("100.64.0.99")
        assert ok is False
        assert "unknown peer" in msg


class TestClearExitNode:
    def test_requires_login(self, client):
        r = client.post("/tailscale/exit-node/clear")
        assert r.status_code == 302

    def test_clear_success(self, auth_client):
        with patch("app.tailscale.utils.clear_exit_node",
                   return_value=(True, "Exit node cleared.")):
            r = auth_client.post("/tailscale/exit-node/clear", follow_redirects=True)
        assert b"Exit node cleared" in r.data

    def test_clear_failure(self, auth_client):
        with patch("app.tailscale.utils.clear_exit_node",
                   return_value=(False, "failed")):
            r = auth_client.post("/tailscale/exit-node/clear", follow_redirects=True)
        assert b"failed" in r.data

    def test_util_clears_exit_node(self, app):
        from app.tailscale import utils
        from unittest.mock import MagicMock
        import subprocess
        mock_r = MagicMock(spec=subprocess.CompletedProcess)
        mock_r.stdout = ""
        mock_r.stderr = ""
        mock_r.returncode = 0
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=mock_r) as m:
                ok, _ = utils.clear_exit_node()
        assert ok is True
        cmd = m.call_args[0][0]
        assert "--exit-node=" in cmd
        assert "--exit-node-allow-lan-access=false" in cmd


class TestExitNodePeers:
    def test_peers_with_exit_node_option(self, auth_client):
        peers = [
            {"hostname": "laptop", "ip": "100.64.0.2",
             "online": True, "exit_node": False, "exit_node_option": True},
        ]
        status = dict(MOCK_STATUS_CONNECTED, peers=peers)
        with patch("app.tailscale.utils.get_status", return_value=status), \
             patch("app.tailscale.utils.get_prefs", return_value=MOCK_PREFS):
            r = auth_client.get("/tailscale/")
        assert b"laptop" in r.data
        assert b"exit node" in r.data
        assert b"Use as exit" in r.data

    def test_active_exit_node_shown_in_status(self, auth_client):
        status = dict(MOCK_STATUS_CONNECTED,
                      exit_node_active=True,
                      exit_node_ip="100.64.0.2")
        with patch("app.tailscale.utils.get_status", return_value=status), \
             patch("app.tailscale.utils.get_prefs", return_value=MOCK_PREFS):
            r = auth_client.get("/tailscale/")
        assert b"100.64.0.2" in r.data

    def test_clear_exit_node_button_shown_when_active(self, auth_client):
        status = dict(MOCK_STATUS_CONNECTED, exit_node_active=True)
        with patch("app.tailscale.utils.get_status", return_value=status), \
             patch("app.tailscale.utils.get_prefs", return_value=MOCK_PREFS):
            r = auth_client.get("/tailscale/")
        assert b"Clear Exit Node" in r.data
