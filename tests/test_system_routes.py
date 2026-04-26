from unittest.mock import patch
import json


MOCK_INFO = {
    "hostname": "raspberrypi",
    "uptime": "3h 20m",
    "cpu_percent": 15.0,
    "cpu_temp": "52.3",
    "memory_total_mb": 4096,
    "memory_used_mb": 1024,
    "memory_percent": 25.0,
    "disk_total_gb": 32,
    "disk_used_gb": 8,
    "disk_percent": 25.0,
}


class TestSystemIndex:
    def test_requires_login(self, client):
        r = client.get("/system/")
        assert r.status_code == 302

    def test_renders(self, auth_client):
        with patch("app.system.utils.get_full_info", return_value=MOCK_INFO):
            r = auth_client.get("/system/")
        assert r.status_code == 200
        assert b"raspberrypi" in r.data


class TestSetHostname:
    def test_valid_hostname(self, auth_client):
        with patch("app.system.utils.set_hostname", return_value=(True, "Hostname updated.")):
            r = auth_client.post("/system/hostname", data={"hostname": "mypi"},
                                 follow_redirects=True)
        assert r.status_code == 200

    def test_invalid_hostname_rejected(self, auth_client):
        for bad in ["has space", "-bad", "", "has.dot"]:
            with patch("app.system.utils.set_hostname", return_value=(True, "")) as mock_fn:
                r = auth_client.post("/system/hostname", data={"hostname": bad},
                                     follow_redirects=True)
            # Should not call the actual utility with bad input
            mock_fn.assert_not_called()

    def test_injection_hostname_rejected(self, auth_client):
        with patch("app.system.utils.set_hostname", return_value=(True, "")) as mock_fn:
            auth_client.post("/system/hostname",
                             data={"hostname": "good;rm -rf /"},
                             follow_redirects=True)
        mock_fn.assert_not_called()


class TestSystemUpdate:
    def test_update_success(self, auth_client):
        with patch("app.system.utils.run_update", return_value=(True, "Update complete.")):
            r = auth_client.post("/system/update", follow_redirects=True)
        assert b"Update complete" in r.data

    def test_update_failure(self, auth_client):
        with patch("app.system.utils.run_update", return_value=(False, "apt-get failed.")):
            r = auth_client.post("/system/update", follow_redirects=True)
        assert b"apt-get failed" in r.data


class TestCheckUpdates:
    def test_returns_json(self, auth_client):
        with patch("app.system.utils.check_updates", return_value="3 package(s) can be upgraded."):
            r = auth_client.get("/system/check-updates")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "3 package" in data["message"]


class TestSystemLogs:
    def test_returns_json(self, auth_client):
        with patch("app.system.utils.get_logs", return_value="2024-01-01 systemd: started"):
            r = auth_client.get("/system/logs?lines=50")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "systemd" in data["logs"]

    def test_lines_capped_at_500(self, auth_client):
        with patch("app.system.utils.get_logs", return_value="") as mock_fn:
            auth_client.get("/system/logs?lines=9999")
        mock_fn.assert_called_once_with(500, "")


class TestReboot:
    def test_reboot_calls_utility(self, auth_client):
        with patch("app.system.utils.reboot", return_value=(True, "Rebooting...")) as mock_fn:
            r = auth_client.post("/system/reboot", follow_redirects=True)
        mock_fn.assert_called_once()
        assert r.status_code == 200


class TestShutdown:
    def test_shutdown_calls_utility(self, auth_client):
        with patch("app.system.utils.shutdown", return_value=(True, "Shutting down...")) as mock_fn:
            r = auth_client.post("/system/shutdown", follow_redirects=True)
        mock_fn.assert_called_once()
        assert r.status_code == 200
