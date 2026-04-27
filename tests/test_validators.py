import pytest
from app.validators import (
    ValidationError,
    validate_ip,
    validate_interface,
    validate_hostname,
    validate_ssid,
    validate_bssid,
    validate_url,
    validate_cidr_list,
    validate_priority,
    validate_lease_time,
    validate_tunnel_name,
    validate_service_name,
)


class TestValidateIp:
    def test_valid_ips(self):
        assert validate_ip("192.168.50.1") == "192.168.50.1"
        assert validate_ip("8.8.8.8") == "8.8.8.8"
        assert validate_ip("  10.0.0.1  ") == "10.0.0.1"

    def test_invalid_ips(self):
        for bad in ["not-an-ip", "999.999.999.999", "192.168.1", "", "192.168.1.1.1"]:
            with pytest.raises(ValidationError):
                validate_ip(bad)

    def test_injection_attempt(self):
        with pytest.raises(ValidationError):
            validate_ip("1.1.1.1; rm -rf /")


class TestValidateInterface:
    def test_valid(self):
        assert validate_interface("wlan0") == "wlan0"
        assert validate_interface("eth0") == "eth0"
        assert validate_interface("wlan1") == "wlan1"

    def test_invalid(self):
        for bad in ["", "eth 0", "eth0; ls", "a" * 16, "eth0|evil"]:
            with pytest.raises(ValidationError):
                validate_interface(bad)


class TestValidateHostname:
    def test_valid(self):
        assert validate_hostname("raspberrypi") == "raspberrypi"
        assert validate_hostname("my-pi-3") == "my-pi-3"
        assert validate_hostname("Pi1") == "Pi1"

    def test_invalid(self):
        for bad in ["", "-bad", "bad-", "has space", "has.dot", "a" * 64]:
            with pytest.raises(ValidationError):
                validate_hostname(bad)

    def test_injection(self):
        with pytest.raises(ValidationError):
            validate_hostname("good;evil")


class TestValidateSsid:
    def test_valid(self):
        assert validate_ssid("MyWiFi") == "MyWiFi"
        assert validate_ssid("Network with spaces") == "Network with spaces"
        assert validate_ssid("a" * 32) == "a" * 32

    def test_empty(self):
        with pytest.raises(ValidationError):
            validate_ssid("")
        with pytest.raises(ValidationError):
            validate_ssid("   ")

    def test_too_long(self):
        with pytest.raises(ValidationError):
            validate_ssid("a" * 33)


class TestValidateBssid:
    def test_valid(self):
        assert validate_bssid("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
        assert validate_bssid("00:1A:2B:3C:4D:5E") == "00:1A:2B:3C:4D:5E"

    def test_invalid(self):
        for bad in ["not-a-mac", "00:11:22:33:44", "GG:HH:II:JJ:KK:LL"]:
            with pytest.raises(ValidationError):
                validate_bssid(bad)


class TestValidateUrl:
    def test_valid(self):
        assert validate_url("https://controlplane.tailscale.com") == "https://controlplane.tailscale.com"
        assert validate_url("https://headscale.example.com") == "https://headscale.example.com"
        assert validate_url("http://192.168.1.100:8080") == "http://192.168.1.100:8080"

    def test_no_scheme(self):
        with pytest.raises(ValidationError):
            validate_url("headscale.example.com")

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError):
            validate_url("ftp://example.com")

    def test_injection_chars(self):
        for bad in [
            "https://ok.com;evil",
            "https://ok.com|evil",
            "https://ok.com`evil`",
            "https://ok.com$(evil)",
        ]:
            with pytest.raises(ValidationError):
                validate_url(bad)

    def test_empty(self):
        with pytest.raises(ValidationError):
            validate_url("")


class TestValidateCidrList:
    def test_valid(self):
        assert validate_cidr_list("192.168.50.0/24") == "192.168.50.0/24"
        assert validate_cidr_list("192.168.0.0/16,10.0.0.0/8") == "192.168.0.0/16,10.0.0.0/8"
        assert validate_cidr_list("") == ""

    def test_invalid(self):
        with pytest.raises(ValidationError):
            validate_cidr_list("not-a-cidr")
        with pytest.raises(ValidationError):
            validate_cidr_list("192.168.1.1/99")

    def test_injection(self):
        with pytest.raises(ValidationError):
            validate_cidr_list("192.168.1.0/24;rm -rf /")


class TestValidatePriority:
    def test_valid(self):
        assert validate_priority(10) == 10
        assert validate_priority("50") == 50
        assert validate_priority(1) == 1
        assert validate_priority(9999) == 9999

    def test_out_of_range(self):
        with pytest.raises(ValidationError):
            validate_priority(0)
        with pytest.raises(ValidationError):
            validate_priority(10000)

    def test_non_integer(self):
        with pytest.raises(ValidationError):
            validate_priority("abc")


class TestValidateLeaseTime:
    def test_valid(self):
        for v in ["1h", "6h", "12h", "24h", "48h"]:
            assert validate_lease_time(v) == v

    def test_invalid(self):
        for bad in ["2h", "1d", "never", "", "24H"]:
            with pytest.raises(ValidationError):
                validate_lease_time(bad)


class TestValidateTunnelName:
    def test_valid(self):
        assert validate_tunnel_name("wg0") == "wg0"
        assert validate_tunnel_name("vpn-home") == "vpn-home"
        assert validate_tunnel_name("wg_office") == "wg_office"
        assert validate_tunnel_name("a" * 15) == "a" * 15
        assert validate_tunnel_name("  wg0  ") == "wg0"

    def test_empty(self):
        with pytest.raises(ValidationError):
            validate_tunnel_name("")
        with pytest.raises(ValidationError):
            validate_tunnel_name("   ")

    def test_too_long(self):
        with pytest.raises(ValidationError):
            validate_tunnel_name("a" * 16)

    def test_invalid_chars(self):
        for bad in ["wg 0", "wg0;evil", "wg0|x", "wg0/etc", "../evil", "wg0`cmd`"]:
            with pytest.raises(ValidationError):
                validate_tunnel_name(bad)


class TestValidateServiceName:
    def test_valid(self):
        assert validate_service_name("wifiproxy") == "wifiproxy"
        assert validate_service_name("wg-quick@wg0") == "wg-quick@wg0"
        assert validate_service_name("NetworkManager") == "NetworkManager"
        assert validate_service_name("dnsmasq.service") == "dnsmasq.service"
        assert validate_service_name("") == ""

    def test_strips_whitespace(self):
        assert validate_service_name("  wifiproxy  ") == "wifiproxy"

    def test_injection_rejected(self):
        for bad in ["wifiproxy;id", "svc|cat /etc/passwd", "svc$(id)", "svc`id`", "svc\nother"]:
            with pytest.raises(ValidationError):
                validate_service_name(bad)
