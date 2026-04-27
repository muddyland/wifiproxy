"""Route tests for the WireGuard blueprint."""
import io
from unittest.mock import patch


TUNNELS_ACTIVE = [{"name": "wg0", "active": True, "autostart": False,
                   "stats": "interface: wg0"}]
TUNNELS_INACTIVE = [{"name": "vpn0", "active": False, "autostart": True}]
TUNNELS_EMPTY = []


class TestWireguardIndex:
    def test_requires_login(self, client):
        r = client.get("/wireguard/")
        assert r.status_code == 302

    def test_renders_when_installed(self, auth_client):
        with patch("app.wireguard.utils.is_installed", return_value=True), \
             patch("app.wireguard.utils.get_tunnels", return_value=TUNNELS_EMPTY), \
             patch("app.wireguard.utils.get_stats", return_value=""):
            r = auth_client.get("/wireguard/")
        assert r.status_code == 200
        assert b"WireGuard" in r.data

    def test_shows_not_installed_banner(self, auth_client):
        with patch("app.wireguard.utils.is_installed", return_value=False), \
             patch("app.wireguard.utils.get_tunnels", return_value=TUNNELS_EMPTY):
            r = auth_client.get("/wireguard/")
        assert b"Not installed" in r.data

    def test_shows_active_tunnel(self, auth_client):
        with patch("app.wireguard.utils.is_installed", return_value=True), \
             patch("app.wireguard.utils.get_tunnels", return_value=TUNNELS_ACTIVE), \
             patch("app.wireguard.utils.get_stats", return_value="interface: wg0"):
            r = auth_client.get("/wireguard/")
        assert b"wg0" in r.data
        assert b"connected" in r.data

    def test_shows_inactive_tunnel(self, auth_client):
        with patch("app.wireguard.utils.is_installed", return_value=True), \
             patch("app.wireguard.utils.get_tunnels", return_value=TUNNELS_INACTIVE), \
             patch("app.wireguard.utils.get_stats", return_value=""):
            r = auth_client.get("/wireguard/")
        assert b"vpn0" in r.data
        assert b"autostart" in r.data


class TestWireguardUpload:
    def _post(self, auth_client, name, content=b"[Interface]\nPrivateKey=x\n"):
        data = {
            "name": name,
            "config": (io.BytesIO(content), "wg0.conf"),
        }
        return auth_client.post("/wireguard/upload", data=data,
                                content_type="multipart/form-data",
                                follow_redirects=True)

    def test_requires_login(self, client):
        r = client.post("/wireguard/upload")
        assert r.status_code == 302

    def test_valid_upload(self, auth_client):
        with patch("app.wireguard.utils.save_config",
                   return_value=(True, "Config saved as wg0.conf")):
            r = self._post(auth_client, "wg0")
        assert b"Config saved" in r.data

    def test_invalid_tunnel_name_rejected(self, auth_client):
        r = self._post(auth_client, "bad name!")
        assert r.status_code == 200
        assert b"Tunnel name" in r.data or b"invalid" in r.data.lower()

    def test_empty_tunnel_name_rejected(self, auth_client):
        r = self._post(auth_client, "")
        assert r.status_code == 200

    def test_oversized_file_rejected(self, auth_client):
        big = b"x" * (65537)
        r = self._post(auth_client, "wg0", content=big)
        assert b"too large" in r.data or b"64 KB" in r.data

    def test_non_utf8_file_rejected(self, auth_client):
        r = self._post(auth_client, "wg0", content=b"\xff\xfe")
        assert b"UTF-8" in r.data

    def test_no_file_rejected(self, auth_client):
        r = auth_client.post("/wireguard/upload",
                             data={"name": "wg0"},
                             content_type="multipart/form-data",
                             follow_redirects=True)
        assert b"No file" in r.data

    def test_save_failure_flashes_error(self, auth_client):
        with patch("app.wireguard.utils.save_config",
                   return_value=(False, "permission denied")):
            r = self._post(auth_client, "wg0")
        assert b"permission denied" in r.data


class TestWireguardConnect:
    def test_requires_login(self, client):
        r = client.post("/wireguard/connect/wg0")
        assert r.status_code == 302

    def test_connect_success(self, auth_client):
        with patch("app.wireguard.utils.connect", return_value=(True, "")):
            r = auth_client.post("/wireguard/connect/wg0", follow_redirects=True)
        assert r.status_code == 200

    def test_connect_failure_shows_message(self, auth_client):
        with patch("app.wireguard.utils.connect",
                   return_value=(False, "RTNETLINK: File exists")):
            r = auth_client.post("/wireguard/connect/wg0", follow_redirects=True)
        assert b"RTNETLINK" in r.data

    def test_invalid_name_rejected(self, auth_client):
        r = auth_client.post("/wireguard/connect/bad name!", follow_redirects=True)
        assert b"Invalid" in r.data


class TestWireguardDisconnect:
    def test_disconnect_success(self, auth_client):
        with patch("app.wireguard.utils.disconnect", return_value=(True, "")):
            r = auth_client.post("/wireguard/disconnect/wg0", follow_redirects=True)
        assert r.status_code == 200

    def test_disconnect_failure(self, auth_client):
        with patch("app.wireguard.utils.disconnect",
                   return_value=(False, "not found")):
            r = auth_client.post("/wireguard/disconnect/wg0", follow_redirects=True)
        assert b"not found" in r.data

    def test_invalid_name_rejected(self, auth_client):
        r = auth_client.post("/wireguard/disconnect/bad!name",
                             follow_redirects=True)
        assert b"Invalid" in r.data


class TestWireguardAutostart:
    def test_enable_autostart(self, auth_client):
        with patch("app.wireguard.utils.set_autostart", return_value=(True, "")) as m:
            auth_client.post("/wireguard/autostart/wg0",
                             data={"enable": "1"},
                             follow_redirects=True)
        m.assert_called_once_with("wg0", True)

    def test_disable_autostart(self, auth_client):
        with patch("app.wireguard.utils.set_autostart", return_value=(True, "")) as m:
            auth_client.post("/wireguard/autostart/wg0",
                             data={"enable": "0"},
                             follow_redirects=True)
        m.assert_called_once_with("wg0", False)


class TestWireguardDelete:
    def test_delete_success(self, auth_client):
        with patch("app.wireguard.utils.delete", return_value=(True, "Deleted wg0.")):
            r = auth_client.post("/wireguard/delete/wg0", follow_redirects=True)
        assert b"Deleted wg0" in r.data

    def test_delete_failure(self, auth_client):
        with patch("app.wireguard.utils.delete",
                   return_value=(False, "File not found")):
            r = auth_client.post("/wireguard/delete/wg0", follow_redirects=True)
        assert b"File not found" in r.data

    def test_invalid_name_rejected(self, auth_client):
        r = auth_client.post("/wireguard/delete/bad!", follow_redirects=True)
        assert b"Invalid" in r.data


class TestWireguardStats:
    def test_returns_json(self, auth_client):
        with patch("app.wireguard.utils.get_stats", return_value="interface: wg0"):
            r = auth_client.get("/wireguard/stats/wg0")
        assert r.status_code == 200
        data = r.get_json()
        assert "output" in data
        assert "wg0" in data["output"]

    def test_requires_login(self, client):
        r = client.get("/wireguard/stats/wg0")
        assert r.status_code == 302

    def test_invalid_name_returns_json_error(self, auth_client):
        r = auth_client.get("/wireguard/stats/bad name!")
        assert r.status_code == 200
        data = r.get_json()
        assert "Invalid" in data["output"]
