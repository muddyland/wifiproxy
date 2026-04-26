"""Verify that security headers are present on every authenticated response."""


class TestSecurityHeaders:
    def _get_headers(self, auth_client):
        from unittest.mock import patch
        with patch("app.wifi.utils.get_current_connection", return_value={"connected": False}), \
             patch("app.main.routes.wifi_utils.get_current_connection", return_value={"connected": False}), \
             patch("app.main.routes.dhcp_utils.get_bridge_status", return_value={}), \
             patch("app.main.routes.ts_utils.get_status", return_value={"installed": False}), \
             patch("app.main.routes.sys_utils.get_quick_info", return_value={}):
            r = auth_client.get("/")
        return r.headers

    def test_x_content_type_options(self, auth_client):
        headers = self._get_headers(auth_client)
        assert headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, auth_client):
        headers = self._get_headers(auth_client)
        assert headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, auth_client):
        headers = self._get_headers(auth_client)
        assert "strict-origin" in headers.get("Referrer-Policy", "")

    def test_content_security_policy_present(self, auth_client):
        headers = self._get_headers(auth_client)
        assert "Content-Security-Policy" in headers

    def test_no_server_header(self, auth_client):
        headers = self._get_headers(auth_client)
        # Should not expose Werkzeug/Python version
        assert "Server" not in headers
