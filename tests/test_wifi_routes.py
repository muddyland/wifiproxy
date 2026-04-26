from unittest.mock import patch, MagicMock
import json
from app.models import WifiNetwork
from app import db


MOCK_NETWORKS = [
    {"ssid": "HomeNet", "signal": 85, "security": "WPA2", "active": True},
    {"ssid": "Neighbor", "signal": 40, "security": "WPA2", "active": False},
]


class TestWifiIndex:
    def test_requires_login(self, client):
        r = client.get("/wifi/")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_renders(self, auth_client):
        with patch("app.wifi.utils.get_current_connection", return_value={"connected": False}):
            r = auth_client.get("/wifi/")
        assert r.status_code == 200
        assert b"WiFi Networks" in r.data


class TestWifiScan:
    def test_returns_json(self, auth_client):
        with patch("app.wifi.utils.scan_networks", return_value=MOCK_NETWORKS):
            r = auth_client.get("/wifi/scan")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert isinstance(data, list)
        assert data[0]["ssid"] == "HomeNet"

    def test_returns_empty_list_on_error(self, auth_client):
        with patch("app.wifi.utils.scan_networks", return_value=[]):
            r = auth_client.get("/wifi/scan")
        assert r.status_code == 200
        assert json.loads(r.data) == []


class TestWifiAdd:
    def test_add_valid_network(self, auth_client, app):
        with patch("app.wifi.utils.set_nm_priority", return_value=True):
            r = auth_client.post("/wifi/add", data={
                "ssid": "NewNetwork",
                "password": "password123",
                "priority": "20",
            }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            net = WifiNetwork.query.filter_by(ssid="NewNetwork").first()
            assert net is not None
            assert net.priority == 20
            assert net.password == "password123"

    def test_add_empty_ssid_rejected(self, auth_client, app):
        r = auth_client.post("/wifi/add", data={
            "ssid": "",
            "password": "pass",
        }, follow_redirects=True)
        assert b"SSID" in r.data or r.status_code in (200, 302)
        with app.app_context():
            assert WifiNetwork.query.count() == 0

    def test_add_ssid_too_long(self, auth_client, app):
        r = auth_client.post("/wifi/add", data={
            "ssid": "a" * 33,
            "password": "pass",
        }, follow_redirects=True)
        with app.app_context():
            assert WifiNetwork.query.count() == 0

    def test_add_invalid_bssid_rejected(self, auth_client, app):
        r = auth_client.post("/wifi/add", data={
            "ssid": "ValidSSID",
            "password": "pass",
            "bssid": "not-a-mac",
        }, follow_redirects=True)
        with app.app_context():
            assert WifiNetwork.query.count() == 0

    def test_add_connect_now(self, auth_client, app):
        with patch("app.wifi.utils.set_nm_priority", return_value=True), \
             patch("app.wifi.utils.connect", return_value=(True, "Connected.")):
            r = auth_client.post("/wifi/add", data={
                "ssid": "QuickConnect",
                "password": "pass",
                "priority": "10",
                "connect_now": "1",
            }, follow_redirects=True)
        assert b"Connected" in r.data

    def test_update_existing_network(self, auth_client, app):
        with app.app_context():
            net = WifiNetwork(ssid="ExistingNet", priority=10)
            net.password = "oldpass"
            db.session.add(net)
            db.session.commit()

        with patch("app.wifi.utils.set_nm_priority", return_value=True):
            auth_client.post("/wifi/add", data={
                "ssid": "ExistingNet",
                "password": "newpass",
                "priority": "50",
            })

        with app.app_context():
            assert WifiNetwork.query.count() == 1
            net = WifiNetwork.query.filter_by(ssid="ExistingNet").first()
            assert net.priority == 50
            assert net.password == "newpass"


class TestWifiConnect:
    def test_connect_success(self, auth_client, app):
        with app.app_context():
            net = WifiNetwork(ssid="TestNet", priority=10)
            net.password = "testpass"
            db.session.add(net)
            db.session.commit()
            net_id = net.id

        with patch("app.wifi.utils.connect", return_value=(True, "Connected.")):
            r = auth_client.post(f"/wifi/connect/{net_id}", follow_redirects=True)
        assert b"Connected" in r.data

    def test_connect_not_found(self, auth_client):
        r = auth_client.post("/wifi/connect/9999")
        assert r.status_code == 404

    def test_connect_failure(self, auth_client, app):
        with app.app_context():
            net = WifiNetwork(ssid="TestNet2", priority=10)
            net.password = "badpass"
            db.session.add(net)
            db.session.commit()
            net_id = net.id

        with patch("app.wifi.utils.connect", return_value=(False, "Authentication failed.")):
            r = auth_client.post(f"/wifi/connect/{net_id}", follow_redirects=True)
        assert b"Authentication failed" in r.data


class TestWifiDelete:
    def test_delete_existing(self, auth_client, app):
        with app.app_context():
            net = WifiNetwork(ssid="DelNet", priority=10)
            net.password = ""
            db.session.add(net)
            db.session.commit()
            net_id = net.id

        with patch("app.wifi.utils.forget_network", return_value=(True, "")):
            r = auth_client.post(f"/wifi/delete/{net_id}", follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            assert db.session.get(WifiNetwork, net_id) is None

    def test_delete_not_found(self, auth_client):
        r = auth_client.post("/wifi/delete/9999")
        assert r.status_code == 404


class TestWifiPriorities:
    def test_priority_reorder(self, auth_client, app):
        with app.app_context():
            nets = [WifiNetwork(ssid=f"Net{i}", priority=i * 10) for i in range(1, 4)]
            for n in nets:
                n.password = ""
                db.session.add(n)
            db.session.commit()
            ids = [n.id for n in nets]

        with patch("app.wifi.utils.set_nm_priority", return_value=True):
            # Reverse the order
            r = auth_client.post("/wifi/priority",
                                 json={"order": list(reversed(ids))},
                                 content_type="application/json")
        assert r.status_code == 200
        assert json.loads(r.data)["ok"] is True

        with app.app_context():
            first = db.session.get(WifiNetwork, ids[0])
            last = db.session.get(WifiNetwork, ids[-1])
            assert last.priority > first.priority

    def test_invalid_payload(self, auth_client):
        r = auth_client.post("/wifi/priority",
                             json={"order": "not-a-list"},
                             content_type="application/json")
        assert r.status_code == 400
