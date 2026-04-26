"""Unit tests for dhcp utils — subprocess and filesystem calls are mocked."""
from unittest.mock import patch, mock_open, MagicMock
import subprocess
from app.dhcp import utils
from app.models import DhcpConfig


def _completed(stdout="", stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


SAMPLE_LEASES = (
    "1234567890 aa:bb:cc:dd:ee:ff 192.168.50.101 laptop *\n"
    "1234567890 11:22:33:44:55:66 192.168.50.102 * *\n"
)


class TestGetLeases:
    def test_parses_leases_file(self, app):
        with app.app_context():
            with patch("builtins.open", mock_open(read_data=SAMPLE_LEASES)), \
                 patch("pathlib.Path.read_text", return_value=SAMPLE_LEASES):
                leases = utils.get_leases()
        assert len(leases) == 2
        assert leases[0]["ip"] == "192.168.50.101"
        assert leases[0]["hostname"] == "laptop"
        assert leases[0]["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_hostname_empty_when_asterisk(self, app):
        with app.app_context():
            with patch("pathlib.Path.read_text", return_value=SAMPLE_LEASES):
                leases = utils.get_leases()
        assert leases[1]["hostname"] == ""

    def test_returns_empty_when_file_missing(self, app):
        with app.app_context():
            with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
                leases = utils.get_leases()
        assert leases == []


class TestGetBridgeStatus:
    def test_all_active(self, app):
        with app.app_context():
            with patch("pathlib.Path.read_text", return_value="1\n"), \
                 patch("app.dhcp.utils._sudo", side_effect=[
                     _completed("MASQUERADE"),       # iptables
                 ]), \
                 patch("subprocess.run", return_value=_completed("active")):
                status = utils.get_bridge_status()
        assert status["forwarding"] is True

    def test_forwarding_off(self, app):
        with app.app_context():
            with patch("pathlib.Path.read_text", return_value="0\n"), \
                 patch("app.dhcp.utils._sudo", return_value=_completed("")), \
                 patch("subprocess.run", return_value=_completed("inactive")):
                status = utils.get_bridge_status()
        assert status["forwarding"] is False


class TestWriteDnsmasqConfig:
    def test_writes_config_and_restarts(self, app):
        with app.app_context():
            cfg = DhcpConfig.query.first()
            with patch("subprocess.run", return_value=_completed()) as mock_run:
                ok, msg = utils.write_dnsmasq_config(cfg)
            assert ok is True
            # Check tee was called and systemctl restart dnsmasq was called
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("tee" in c for c in calls)
            assert any("restart" in c and "dnsmasq" in c for c in calls)

    def test_returns_false_on_tee_failure(self, app):
        with app.app_context():
            cfg = DhcpConfig.query.first()
            with patch("subprocess.run", return_value=_completed("", "Permission denied", 1)):
                ok, msg = utils.write_dnsmasq_config(cfg)
        assert ok is False

    def test_config_content_includes_interface(self, app):
        with app.app_context():
            cfg = DhcpConfig.query.first()
            written = []
            def capture_run(cmd, **kwargs):
                if "tee" in cmd:
                    written.append(kwargs.get("input", ""))
                return _completed()
            with patch("subprocess.run", side_effect=capture_run):
                utils.write_dnsmasq_config(cfg)
        assert any("eth0" in w for w in written)
        assert any("192.168.50.1" in w for w in written)


class TestApplyIptables:
    def test_all_rules_applied(self, app):
        with app.app_context():
            with patch("app.dhcp.utils._sudo", return_value=_completed()) as mock_sudo:
                ok, msg = utils.apply_iptables("wlan0", "eth0")
        assert ok is True
        # Should have called at least 6 commands
        assert mock_sudo.call_count >= 6

    def test_stops_on_failure(self, app):
        with app.app_context():
            with patch("app.dhcp.utils._sudo", return_value=_completed("", "eperm", 1)):
                ok, msg = utils.apply_iptables("wlan0", "eth0")
        assert ok is False
