"""Unit tests for WireGuard utils — subprocess calls are mocked."""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from app.wireguard import utils


def _completed(stdout="", stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


class TestIsInstalled:
    def test_installed(self):
        with patch("app.wireguard.utils.shutil.which", return_value="/usr/bin/wg-quick"):
            assert utils.is_installed() is True

    def test_not_installed(self):
        with patch("app.wireguard.utils.shutil.which", return_value=None):
            assert utils.is_installed() is False


class TestGetActiveInterfaces:
    def test_parses_wireguard_interface(self):
        output = "5: wg0: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420\n"
        with patch("subprocess.run", return_value=_completed(output)):
            result = utils.get_active_interfaces()
        assert "wg0" in result

    def test_parses_multiple_interfaces(self):
        output = "5: wg0: <UP>\n6: wg1: <UP>\n"
        with patch("subprocess.run", return_value=_completed(output)):
            result = utils.get_active_interfaces()
        assert "wg0" in result
        assert "wg1" in result

    def test_empty_when_no_wireguard(self):
        with patch("subprocess.run", return_value=_completed("")):
            result = utils.get_active_interfaces()
        assert result == set()

    def test_exception_returns_empty_set(self):
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = utils.get_active_interfaces()
        assert result == set()


class TestIsAutostart:
    def test_enabled(self):
        with patch("subprocess.run", return_value=_completed("enabled\n")):
            assert utils.is_autostart("wg0") is True

    def test_disabled(self):
        with patch("subprocess.run", return_value=_completed("disabled\n")):
            assert utils.is_autostart("wg0") is False

    def test_exception_returns_false(self):
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert utils.is_autostart("wg0") is False


class TestGetTunnels:
    def test_not_installed_returns_empty(self, app):
        with app.app_context():
            with patch("app.wireguard.utils.is_installed", return_value=False):
                result = utils.get_tunnels()
        assert result == []

    def test_lists_conf_files(self, app):
        mock_conf = MagicMock(spec=Path)
        mock_conf.stem = "wg0"
        with app.app_context():
            with patch("app.wireguard.utils.is_installed", return_value=True), \
                 patch("app.wireguard.utils.get_active_interfaces", return_value={"wg0"}), \
                 patch("app.wireguard.utils.is_autostart", return_value=False), \
                 patch.object(Path, "glob", return_value=[mock_conf]):
                result = utils.get_tunnels()
        assert len(result) == 1
        assert result[0]["name"] == "wg0"
        assert result[0]["active"] is True
        assert result[0]["autostart"] is False

    def test_inactive_tunnel(self, app):
        mock_conf = MagicMock(spec=Path)
        mock_conf.stem = "vpn0"
        with app.app_context():
            with patch("app.wireguard.utils.is_installed", return_value=True), \
                 patch("app.wireguard.utils.get_active_interfaces", return_value=set()), \
                 patch("app.wireguard.utils.is_autostart", return_value=True), \
                 patch.object(Path, "glob", return_value=[mock_conf]):
                result = utils.get_tunnels()
        assert result[0]["active"] is False
        assert result[0]["autostart"] is True


class TestGetStats:
    def test_returns_wg_show_output(self):
        with patch("app.wireguard.utils._sudo",
                   return_value=_completed("interface: wg0\n  public key: abc")):
            result = utils.get_stats("wg0")
        assert "wg0" in result

    def test_exception_returns_error_string(self):
        with patch("app.wireguard.utils._sudo", side_effect=Exception("boom")):
            result = utils.get_stats("wg0")
        assert "boom" in result


class TestApplyNatRules:
    def _run(self, action, wg_iface="wg0", lan_iface="eth0"):
        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            r = MagicMock()
            r.returncode = 1  # simulate "rule not present" for -C checks
            return r
        with patch("subprocess.run", side_effect=fake_run):
            utils._apply_nat_rules(action, wg_iface, lan_iface)
        return calls

    def test_add_inserts_three_rules(self):
        calls = self._run("-A")
        add_calls = [c for c in calls if "-A" in c]
        assert len(add_calls) == 3

    def test_add_includes_masquerade(self):
        calls = self._run("-A")
        assert any("MASQUERADE" in c for c in calls)

    def test_add_includes_forward_rules(self):
        calls = self._run("-A")
        forward_calls = [c for c in calls if "FORWARD" in c]
        assert len(forward_calls) >= 2

    def test_add_skips_existing_rule(self):
        def fake_run(cmd, **kwargs):
            r = MagicMock()
            # -C check succeeds → rule already exists
            r.returncode = 0 if "-C" in cmd else 1
            return r
        with patch("subprocess.run", side_effect=fake_run) as m:
            utils._apply_nat_rules("-A", "wg0", "eth0")
        # No -A calls should have been made since all -C checks passed
        add_calls = [c for c in [call[0][0] for call in m.call_args_list] if "-A" in c]
        assert add_calls == []

    def test_delete_does_not_check_first(self):
        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            r = MagicMock()
            r.returncode = 0
            return r
        with patch("subprocess.run", side_effect=fake_run):
            utils._apply_nat_rules("-D", "wg0", "eth0")
        check_calls = [c for c in calls if "-C" in c]
        assert check_calls == []


class TestHasNatRules:
    def test_returns_true_when_rule_exists(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            assert utils.has_nat_rules("wg0") is True

    def test_returns_false_when_rule_absent(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            assert utils.has_nat_rules("wg0") is False

    def test_returns_false_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert utils.has_nat_rules("wg0") is False


class TestConnect:
    def test_success(self):
        with patch("app.wireguard.utils._sudo", return_value=_completed("", "", 0)), \
             patch("app.wireguard.utils._apply_nat_rules"), \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            ok, msg = utils.connect("wg0")
        assert ok is True
        assert "LAN" in msg

    def test_failure(self):
        with patch("app.wireguard.utils._sudo",
                   return_value=_completed("", "RTNETLINK: File exists", 1)), \
             patch("app.wireguard.utils._apply_nat_rules"), \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            ok, msg = utils.connect("wg0")
        assert ok is False
        assert "RTNETLINK" in msg

    def test_nat_rules_added_on_success(self):
        with patch("app.wireguard.utils._sudo", return_value=_completed("", "", 0)), \
             patch("app.wireguard.utils._apply_nat_rules") as mock_nat, \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            utils.connect("wg0")
        mock_nat.assert_called_once_with("-A", "wg0", "eth0")

    def test_nat_rules_not_added_on_failure(self):
        with patch("app.wireguard.utils._sudo",
                   return_value=_completed("", "error", 1)), \
             patch("app.wireguard.utils._apply_nat_rules") as mock_nat, \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            utils.connect("wg0")
        mock_nat.assert_not_called()

    def test_timeout(self):
        with patch("app.wireguard.utils._sudo",
                   side_effect=subprocess.TimeoutExpired([], 30)), \
             patch("app.wireguard.utils._apply_nat_rules"), \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            ok, msg = utils.connect("wg0")
        assert ok is False
        assert "timed out" in msg.lower()


class TestDisconnect:
    def test_success(self):
        with patch("app.wireguard.utils._sudo", return_value=_completed("", "", 0)), \
             patch("app.wireguard.utils._apply_nat_rules"), \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            ok, _ = utils.disconnect("wg0")
        assert ok is True

    def test_nat_rules_removed_before_down(self):
        order = []
        def fake_nat(action, *a):
            order.append(f"nat:{action}")
        def fake_sudo(cmd, **kwargs):
            order.append(f"sudo:{cmd[0]}")
            return _completed("", "", 0)
        with patch("app.wireguard.utils._apply_nat_rules", side_effect=fake_nat), \
             patch("app.wireguard.utils._sudo", side_effect=fake_sudo), \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            utils.disconnect("wg0")
        assert order[0] == "nat:-D"
        assert "sudo:wg-quick" in order[1]

    def test_failure(self):
        with patch("app.wireguard.utils._sudo",
                   return_value=_completed("", "interface not found", 1)), \
             patch("app.wireguard.utils._apply_nat_rules"), \
             patch("app.wireguard.utils._get_lan_iface", return_value="eth0"):
            ok, msg = utils.disconnect("wg0")
        assert ok is False


class TestSetAutostart:
    def test_enable(self):
        with patch("app.wireguard.utils._sudo", return_value=_completed()) as m:
            ok, _ = utils.set_autostart("wg0", True)
        assert ok is True
        cmd = m.call_args[0][0]
        assert "enable" in cmd
        assert "wg-quick@wg0" in cmd

    def test_disable(self):
        with patch("app.wireguard.utils._sudo", return_value=_completed()) as m:
            ok, _ = utils.set_autostart("wg0", False)
        assert ok is True
        cmd = m.call_args[0][0]
        assert "disable" in cmd

    def test_failure(self):
        with patch("app.wireguard.utils._sudo",
                   return_value=_completed("", "failed", 1)):
            ok, _ = utils.set_autostart("wg0", True)
        assert ok is False


class TestSaveConfig:
    def test_success(self):
        conf_content = "[Interface]\nPrivateKey = abc\n"
        with patch("subprocess.run", return_value=_completed("", "", 0)), \
             patch("app.wireguard.utils._sudo", return_value=_completed()):
            ok, msg = utils.save_config("wg0", conf_content)
        assert ok is True
        assert "wg0" in msg

    def test_tee_failure(self):
        with patch("subprocess.run", return_value=_completed("", "permission denied", 1)):
            ok, msg = utils.save_config("wg0", "[Interface]\n")
        assert ok is False
        assert "permission denied" in msg


class TestDelete:
    def test_deletes_conf(self):
        with patch("app.wireguard.utils.get_active_interfaces", return_value=set()), \
             patch("app.wireguard.utils._sudo", return_value=_completed()) as m:
            ok, msg = utils.delete("wg0")
        assert ok is True
        assert "wg0" in msg

    def test_disconnects_before_delete(self):
        calls = []
        def fake_sudo(cmd, **kwargs):
            calls.append(cmd)
            return _completed()
        with patch("app.wireguard.utils.get_active_interfaces", return_value={"wg0"}), \
             patch("app.wireguard.utils._sudo", side_effect=fake_sudo):
            utils.delete("wg0")
        # First call should be wg-quick down, second should be rm
        assert any("down" in c for c in calls[0])
        assert any("rm" in c for c in calls[1])
