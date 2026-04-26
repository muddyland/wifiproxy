from unittest.mock import patch
import json
from app.models import DhcpConfig
from app import db


MOCK_LEASES = [
    {"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.50.101", "hostname": "laptop", "expires": "1234567890"},
    {"mac": "11:22:33:44:55:66", "ip": "192.168.50.102", "hostname": "", "expires": "1234567890"},
]

MOCK_BRIDGE = {"forwarding": True, "nat_active": True, "dnsmasq_running": True}


class TestDhcpIndex:
    def test_requires_login(self, client):
        r = client.get("/dhcp/")
        assert r.status_code == 302

    def test_renders(self, auth_client):
        with patch("app.dhcp.utils.get_bridge_status", return_value=MOCK_BRIDGE), \
             patch("app.dhcp.utils.get_leases", return_value=MOCK_LEASES):
            r = auth_client.get("/dhcp/")
        assert r.status_code == 200
        assert b"DHCP" in r.data


class TestDhcpSave:
    def _post(self, client, overrides=None):
        data = {
            "lan_interface": "eth0",
            "wan_interface": "wlan0",
            "gateway": "192.168.50.1",
            "subnet_mask": "255.255.255.0",
            "dns1": "8.8.8.8",
            "dns2": "8.8.4.4",
            "range_start": "192.168.50.100",
            "range_end": "192.168.50.200",
            "lease_time": "24h",
        }
        if overrides:
            data.update(overrides)
        with patch("app.dhcp.utils.write_dnsmasq_config", return_value=(True, "OK")), \
             patch("app.dhcp.utils.update_lan_ip", return_value=(True, "")):
            return client.post("/dhcp/save", data=data, follow_redirects=True)

    def test_save_valid_config(self, auth_client, app):
        r = self._post(auth_client)
        assert r.status_code == 200

    def test_invalid_gateway_rejected(self, auth_client):
        r = self._post(auth_client, {"gateway": "not-an-ip"})
        assert b"not a valid IPv4" in r.data

    def test_invalid_interface_rejected(self, auth_client):
        r = self._post(auth_client, {"lan_interface": "eth0; evil"})
        assert b"not a valid interface" in r.data

    def test_invalid_lease_time_rejected(self, auth_client):
        r = self._post(auth_client, {"lease_time": "99h"})
        assert b"Lease time" in r.data

    def test_config_persisted(self, auth_client, app):
        self._post(auth_client, {"dns1": "1.1.1.1"})
        with app.app_context():
            cfg = DhcpConfig.query.first()
            assert cfg.dns1 == "1.1.1.1"


class TestDhcpLeases:
    def test_leases_json(self, auth_client):
        with patch("app.dhcp.utils.get_leases", return_value=MOCK_LEASES):
            r = auth_client.get("/dhcp/leases")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert len(data) == 2
        assert data[0]["ip"] == "192.168.50.101"

    def test_leases_empty(self, auth_client):
        with patch("app.dhcp.utils.get_leases", return_value=[]):
            r = auth_client.get("/dhcp/leases")
        assert json.loads(r.data) == []


class TestReapplyNat:
    def test_reapply_success(self, auth_client):
        with patch("app.dhcp.utils.apply_iptables", return_value=(True, "Rules applied.")):
            r = auth_client.post("/dhcp/reapply-nat", follow_redirects=True)
        assert b"Rules applied" in r.data

    def test_reapply_failure(self, auth_client):
        with patch("app.dhcp.utils.apply_iptables", return_value=(False, "Permission denied.")):
            r = auth_client.post("/dhcp/reapply-nat", follow_redirects=True)
        assert b"Permission denied" in r.data
