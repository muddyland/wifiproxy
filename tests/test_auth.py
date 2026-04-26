import pytest
from app.models import User
from app import db


class TestLogin:
    def test_login_page_renders(self, client):
        r = client.get("/login")
        assert r.status_code == 200
        assert b"WiFi Bridge" in r.data

    def test_login_success(self, client, app):
        with app.app_context():
            u = User.query.filter_by(username="admin").first()
            assert u is not None

        r = client.post("/login", data={"username": "admin", "password": "admin"},
                        follow_redirects=True)
        assert r.status_code == 200
        assert b"Dashboard" in r.data

    def test_login_wrong_password(self, client):
        r = client.post("/login", data={"username": "admin", "password": "wrong"},
                        follow_redirects=True)
        assert b"Invalid username or password" in r.data

    def test_login_wrong_username(self, client):
        r = client.post("/login", data={"username": "notexist", "password": "admin"},
                        follow_redirects=True)
        assert b"Invalid username or password" in r.data

    def test_redirect_to_login_when_unauthenticated(self, client):
        for url in ["/", "/wifi/", "/dhcp/", "/tailscale/", "/system/"]:
            r = client.get(url)
            assert r.status_code in (301, 302)
            assert "/login" in r.headers["Location"]

    def test_logout(self, auth_client):
        r = auth_client.get("/logout", follow_redirects=True)
        assert b"WiFi Bridge" in r.data
        # After logout, / should redirect to login
        r2 = auth_client.get("/")
        assert r2.status_code in (301, 302)

    def test_open_redirect_blocked(self, client, app):
        with app.app_context():
            pass
        r = client.post(
            "/login?next=https://evil.com",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        location = r.headers.get("Location", "")
        assert "evil.com" not in location


class TestChangePassword:
    def test_change_password_success(self, auth_client, app):
        r = auth_client.post("/change-password", data={
            "current_password": "admin",
            "new_password": "newpassword1",
            "confirm_password": "newpassword1",
        }, follow_redirects=True)
        assert b"Password updated" in r.data

        with app.app_context():
            u = User.query.filter_by(username="admin").first()
            assert u.check_password("newpassword1")

    def test_change_password_wrong_current(self, auth_client):
        r = auth_client.post("/change-password", data={
            "current_password": "wrong",
            "new_password": "newpassword1",
            "confirm_password": "newpassword1",
        }, follow_redirects=True)
        assert b"Current password is incorrect" in r.data

    def test_change_password_mismatch(self, auth_client):
        r = auth_client.post("/change-password", data={
            "current_password": "admin",
            "new_password": "newpassword1",
            "confirm_password": "different",
        }, follow_redirects=True)
        assert b"Passwords do not match" in r.data

    def test_change_password_too_short(self, auth_client):
        r = auth_client.post("/change-password", data={
            "current_password": "admin",
            "new_password": "short",
            "confirm_password": "short",
        }, follow_redirects=True)
        assert b"at least 8 characters" in r.data
