"""Unit tests for tailscale utils — subprocess calls are mocked."""
import json
from unittest.mock import patch, MagicMock
import subprocess
from app.tailscale import utils


def _completed(stdout="", stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


SAMPLE_STATUS_JSON = json.dumps({
    "BackendState": "Running",
    "Self": {
        "TailscaleIPs": ["100.64.0.1"],
        "HostName": "raspberrypi",
    },
    "CurrentTailnet": {"MagicDNSSuffix": "example.ts.net"},
    "Peer": {
        "abc123": {
            "HostName": "laptop",
            "TailscaleIPs": ["100.64.0.2"],
            "Online": True,
            "ExitNode": False,
        }
    },
    "ExitNodeStatus": None,
})

NEEDS_LOGIN_JSON = json.dumps({
    "BackendState": "NeedsLogin",
    "AuthURL": "https://headscale.example.com/register/abc",
    "Self": {},
    "Peer": {},
})


class TestGetStatus:
    def test_parses_connected_status(self, app):
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=True), \
                 patch("app.tailscale.utils._run_plain",
                        return_value=_completed(SAMPLE_STATUS_JSON)):
                status = utils.get_status()
        assert status["connected"] is True
        assert status["ip"] == "100.64.0.1"
        assert status["hostname"] == "raspberrypi"
        assert status["backend_state"] == "Running"
        assert len(status["peers"]) == 1
        assert status["peers"][0]["hostname"] == "laptop"

    def test_falls_back_to_sudo_on_error(self, app):
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=True), \
                 patch("app.tailscale.utils._run_plain",
                        return_value=_completed("", "permission denied", 1)), \
                 patch("app.tailscale.utils._run",
                        return_value=_completed(SAMPLE_STATUS_JSON)):
                status = utils.get_status()
        assert status["connected"] is True

    def test_needs_login_state(self, app):
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=True), \
                 patch("app.tailscale.utils._run_plain",
                        return_value=_completed(NEEDS_LOGIN_JSON, returncode=1)), \
                 patch("app.tailscale.utils._run",
                        return_value=_completed(NEEDS_LOGIN_JSON)):
                status = utils.get_status()
        assert status["needs_auth"] is True
        assert status["connected"] is False
        assert status["auth_url"] == "https://headscale.example.com/register/abc"
        assert status["backend_state"] == "NeedsLogin"

    def test_not_installed(self, app):
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=False):
                status = utils.get_status()
        assert status["installed"] is False
        assert status["connected"] is False

    def test_parse_error_returns_safe_defaults(self, app):
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=True), \
                 patch("app.tailscale.utils._run_plain",
                        return_value=_completed("bad json")), \
                 patch("app.tailscale.utils._run",
                        return_value=_completed("bad json")):
                status = utils.get_status()
        assert status["connected"] is False
        assert status["needs_auth"] is False

    def test_disconnected_state(self, app):
        disconnected = json.dumps({"BackendState": "Stopped", "Self": {}, "Peer": {}})
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=True), \
                 patch("app.tailscale.utils._run_plain",
                        return_value=_completed(disconnected)):
                status = utils.get_status()
        assert status["connected"] is False
        assert status["needs_auth"] is False
        assert status["backend_state"] == "Stopped"

    def test_tailscale_ips_at_top_level(self, app):
        data = json.dumps({
            "BackendState": "Running",
            "TailscaleIPs": ["100.64.1.1"],
            "Self": {"HostName": "pi"},
            "Peer": {},
        })
        with app.app_context():
            with patch("app.tailscale.utils.is_installed", return_value=True), \
                 patch("app.tailscale.utils._run_plain", return_value=_completed(data)):
                status = utils.get_status()
        assert status["ip"] == "100.64.1.1"


class TestLogin:
    def test_login_success(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed("Success")):
                ok, msg = utils.login("https://controlplane.tailscale.com")
        assert ok is True

    def test_login_returns_url_for_headscale(self, app):
        url = "https://headscale.example.com/register/nodeid"
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed("", url, 1)):
                ok, msg = utils.login("https://headscale.example.com")
        assert ok is False
        assert msg == url

    def test_login_builds_correct_flags(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed()) as mock_run:
                utils.login(
                    login_server="https://headscale.example.com",
                    auth_key="mykey",
                    advertise_exit_node=True,
                    accept_routes=True,
                    advertise_routes="192.168.50.0/24",
                )
        cmd = mock_run.call_args[0][0]
        assert "--login-server=https://headscale.example.com" in cmd
        assert "--authkey=mykey" in cmd
        assert "--advertise-exit-node" in cmd
        assert "--accept-routes" in cmd
        assert "--advertise-routes=192.168.50.0/24" in cmd

    def test_login_no_auth_key_omits_flag(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed()) as mock_run:
                utils.login("https://example.com", auth_key="")
        cmd = mock_run.call_args[0][0]
        assert not any("authkey" in c for c in cmd)

    def test_timeout_handled(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", side_effect=subprocess.TimeoutExpired([], 60)):
                ok, msg = utils.login("https://example.com")
        assert ok is False
        assert "timed out" in msg.lower()


class TestDown:
    def test_down_success(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed()):
                ok, _ = utils.down()
        assert ok is True

    def test_down_failure(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed("", "error", 1)):
                ok, msg = utils.down()
        assert ok is False


class TestLogout:
    def test_logout_success(self, app):
        with app.app_context():
            with patch("app.tailscale.utils._run", return_value=_completed()):
                ok, _ = utils.logout()
        assert ok is True
