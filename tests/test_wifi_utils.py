"""Unit tests for wifi utils — all subprocess calls are mocked."""
from unittest.mock import patch, MagicMock
import subprocess
from app.wifi import utils


def _completed(stdout="", stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def _ml(*entries):
    """Build nmcli multiline output from (ssid, signal, security, active) tuples."""
    lines = []
    for ssid, signal, security, active in entries:
        lines += [
            f"SSID:     {ssid}",
            f"SIGNAL:   {signal}",
            f"SECURITY: {security}",
            f"ACTIVE:   {active}",
            "",
        ]
    return "\n".join(lines)


class TestScanNetworks:
    def test_parses_output(self, app):
        nmcli_output = _ml(
            ("HomeNet", "85", "WPA2", "yes"),
            ("Neighbor", "40", "WPA2", "no"),
            ("OpenNet", "60", "Open", "no"),
        )
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed(nmcli_output)):
                results = utils.scan_networks()

        assert len(results) == 3
        assert results[0]["ssid"] == "HomeNet"
        assert results[0]["signal"] == 85
        assert results[0]["active"] is True

    def test_deduplicates_ssids(self, app):
        nmcli_output = _ml(("Dup", "80", "WPA2", "no"), ("Dup", "70", "WPA2", "no"))
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed(nmcli_output)):
                results = utils.scan_networks()
        assert len(results) == 1

    def test_returns_empty_on_error(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", side_effect=Exception("no wifi")):
                results = utils.scan_networks()
        assert results == []

    def test_sorted_by_signal_descending(self, app):
        nmcli_output = _ml(
            ("Weak", "20", "WPA2", "no"),
            ("Strong", "90", "WPA2", "no"),
            ("Mid", "50", "WPA2", "no"),
        )
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed(nmcli_output)):
                results = utils.scan_networks()
        signals = [r["signal"] for r in results]
        assert signals == sorted(signals, reverse=True)

    def test_skips_empty_ssids(self, app):
        nmcli_output = _ml(("", "80", "WPA2", "no"), ("RealNet", "70", "WPA2", "no"))
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed(nmcli_output)):
                results = utils.scan_networks()
        assert all(r["ssid"] for r in results)


class TestGetCurrentConnection:
    def test_connected(self, app):
        show_output = "GENERAL.CONNECTION:HomeNet\n"
        ip_output = "IP4.ADDRESS[1]:192.168.1.5/24\n"
        wifi_output = "HomeNet:85:yes\n"

        with app.app_context():
            with patch("app.wifi.utils._run", side_effect=[
                _completed(show_output),
                _completed(ip_output),
                _completed(wifi_output),
            ]):
                result = utils.get_current_connection()

        assert result["connected"] is True
        assert result["ssid"] == "HomeNet"
        assert result["ip"] == "192.168.1.5"
        assert result["signal"] == 85

    def test_disconnected(self, app):
        show_output = "GENERAL.CONNECTION:--\n"
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed(show_output)):
                result = utils.get_current_connection()
        assert result["connected"] is False
        assert result["ssid"] is None

    def test_error_returns_defaults(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", side_effect=Exception("nmcli not found")):
                result = utils.get_current_connection()
        assert result["connected"] is False


class TestConnect:
    def test_connect_success(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed("Device wlan0 connected")):
                ok, msg = utils.connect("HomeNet", "password123")
        assert ok is True

    def test_connect_failure(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed("", "Error: wrong key", 1)):
                ok, msg = utils.connect("HomeNet", "wrongpass")
        assert ok is False
        assert "wrong key" in msg

    def test_connect_timeout(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", side_effect=subprocess.TimeoutExpired([], 30)):
                ok, msg = utils.connect("HomeNet", "pass")
        assert ok is False
        assert "timed out" in msg.lower()

    def test_connect_with_bssid(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed("connected")) as mock_run:
                utils.connect("HomeNet", "pass", bssid="AA:BB:CC:DD:EE:FF")
        cmd = mock_run.call_args[0][0]
        assert "bssid" in cmd
        assert "AA:BB:CC:DD:EE:FF" in cmd


class TestDisconnect:
    def test_disconnect_success(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed("disconnected")):
                ok, _ = utils.disconnect()
        assert ok is True

    def test_disconnect_failure(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed("", "Error", 1)):
                ok, _ = utils.disconnect()
        assert ok is False


class TestSetNmPriority:
    def test_success(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed()):
                result = utils.set_nm_priority("HomeNet", 50)
        assert result is True

    def test_failure(self, app):
        with app.app_context():
            with patch("app.wifi.utils._run", return_value=_completed("", "not found", 1)):
                result = utils.set_nm_priority("Missing", 10)
        assert result is False
