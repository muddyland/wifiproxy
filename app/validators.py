"""Input validation helpers. All user-supplied values that reach subprocess
commands must pass through these before use."""

import ipaddress
import re
from urllib.parse import urlparse

# Interfaces: alphanumeric + underscore/hyphen, max 15 chars (Linux IFNAMSIZ-1)
_IFACE_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,15}$')
# Hostname: RFC-952/1123
_HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$')
# BSSID: standard MAC address notation
_BSSID_RE = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
# WireGuard tunnel name: Linux interface name rules
_TUNNEL_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,15}$')
# systemd service unit name: letters, digits, : - _ . @ /  (covers wg-quick@wg0, etc.)
_SERVICE_NAME_RE = re.compile(r'^[a-zA-Z0-9:_\-\.@/]{1,128}$')
# Domain/FQDN for dig: labels of a-z0-9 and hyphens separated by dots
_DOMAIN_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,251}[a-zA-Z0-9])?\.?$')
_DNS_RECORD_TYPES = frozenset({
    "A", "AAAA", "MX", "TXT", "NS", "CNAME", "PTR", "SOA", "ANY", "SRV", "CAA"
})


class ValidationError(ValueError):
    pass


def validate_ip(value: str, field: str = "IP address") -> str:
    try:
        ipaddress.IPv4Address(value.strip())
        return value.strip()
    except ValueError as exc:
        raise ValidationError(
            f"{field}: '{value}' is not a valid IPv4 address."
        ) from exc


def validate_interface(value: str, field: str = "Interface") -> str:
    value = value.strip()
    if not _IFACE_RE.match(value):
        raise ValidationError(f"{field}: '{value}' is not a valid interface name.")
    return value


def validate_hostname(value: str) -> str:
    value = value.strip()
    if not _HOSTNAME_RE.match(value):
        raise ValidationError(
            f"Hostname '{value}' is invalid. Use letters, numbers, and hyphens only."
        )
    return value


def validate_ssid(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValidationError("SSID cannot be empty.")
    if len(value) > 32:
        raise ValidationError("SSID must be 32 characters or fewer.")
    return value


def validate_bssid(value: str) -> str:
    value = value.strip().upper()
    if not _BSSID_RE.match(value):
        raise ValidationError(f"BSSID '{value}' must be in AA:BB:CC:DD:EE:FF format.")
    return value


def validate_url(value: str, field: str = "URL") -> str:
    value = value.strip()
    try:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise ValidationError(f"{field}: must start with http:// or https://")
        if not parsed.netloc:
            raise ValidationError(f"{field}: missing host.")
        # Reject URLs with shell-special characters (extra safety belt)
        bad_chars = set(';|&`$(){}[]<>\\\'"\n\r\t')
        if any(c in value for c in bad_chars):
            raise ValidationError(f"{field}: contains invalid characters.")
        return value
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"{field}: '{value}' is not a valid URL.") from exc


def validate_cidr_list(value: str) -> str:
    """Validate comma-separated CIDR list (e.g. '192.168.50.0/24,10.0.0.0/8')."""
    value = value.strip()
    if not value:
        return value
    for part in value.split(","):
        part = part.strip()
        try:
            ipaddress.IPv4Network(part, strict=False)
        except ValueError as exc:
            raise ValidationError(f"'{part}' is not a valid CIDR network.") from exc
    return value


def validate_priority(value) -> int:
    try:
        p = int(value)
        if not 1 <= p <= 9999:
            raise ValueError("out of range")
        return p
    except (TypeError, ValueError) as exc:
        raise ValidationError("Priority must be an integer between 1 and 9999.") from exc


def validate_tunnel_name(value: str) -> str:
    value = value.strip()
    if not _TUNNEL_NAME_RE.match(value):
        raise ValidationError(
            "Tunnel name must be 1-15 characters: letters, numbers, underscore, hyphen."
        )
    return value


def validate_service_name(value: str) -> str:
    """Validate a systemd unit name passed to journalctl -u."""
    value = value.strip()
    if not value:
        return value
    if not _SERVICE_NAME_RE.match(value):
        raise ValidationError(f"Service name '{value}' contains invalid characters.")
    return value


def validate_domain(value: str) -> str:
    """Validate a domain name or IPv4 address suitable for a dig query."""
    value = value.strip()
    if not value:
        raise ValidationError("Domain cannot be empty.")
    if len(value) > 255:
        raise ValidationError("Domain too long (max 255 characters).")
    try:
        ipaddress.IPv4Address(value)
        return value
    except ValueError:
        pass
    if ".." in value:
        raise ValidationError(f"'{value}' is not a valid domain name.")
    if not _DOMAIN_RE.match(value):
        raise ValidationError(f"'{value}' is not a valid domain name.")
    return value


def validate_dns_record_type(value: str) -> str:
    value = value.strip().upper()
    if value not in _DNS_RECORD_TYPES:
        raise ValidationError(
            f"Unsupported record type '{value}'. "
            f"Allowed: {', '.join(sorted(_DNS_RECORD_TYPES))}."
        )
    return value


def validate_lease_time(value: str) -> str:
    allowed = {"1h", "6h", "12h", "24h", "48h"}
    if value not in allowed:
        raise ValidationError(f"Lease time must be one of: {', '.join(sorted(allowed))}.")
    return value
