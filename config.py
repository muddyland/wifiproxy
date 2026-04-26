import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production-use-a-long-random-string")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{BASE_DIR / 'wifiproxy.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WAN_INTERFACE = os.environ.get("WAN_INTERFACE", "wlan0")
    LAN_INTERFACE = os.environ.get("LAN_INTERFACE", "eth0")
    NM_LAN_CONNECTION = os.environ.get("NM_LAN_CONNECTION", "Ethernet-Share")

    RATELIMIT_STORAGE_URI = "memory://"

    DNSMASQ_CONF = "/etc/dnsmasq.conf"
    DNSMASQ_LEASES = "/var/lib/dnsmasq/dnsmasq.leases"
    IPTABLES_RULES_V4 = "/etc/iptables/rules.v4"
