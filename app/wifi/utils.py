import subprocess
from typing import Optional
from flask import current_app


def _run(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def _sudo(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(["sudo"] + cmd, timeout=timeout)


def scan_networks() -> list[dict]:
    """Return list of visible WiFi networks, sorted by signal strength."""
    try:
        result = _run(
            ["nmcli", "--terse", "--escape", "no",
             "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
             "dev", "wifi", "list", "--rescan", "yes"],
            timeout=20,
        )
        networks = []
        seen: set[str] = set()
        for line in result.stdout.strip().splitlines():
            parts = line.split(":", 3)
            if len(parts) < 4:
                continue
            ssid, signal, security, active = parts
            ssid = ssid.strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            networks.append({
                "ssid": ssid,
                "signal": int(signal) if signal.isdigit() else 0,
                "security": security.strip() or "Open",
                "active": active.strip() == "yes",
            })
        return sorted(networks, key=lambda x: x["signal"], reverse=True)
    except Exception as e:
        current_app.logger.error("WiFi scan error: %s", e)
        return []


def get_current_connection() -> dict:
    """Return info about the current wlan0 connection."""
    wan = current_app.config["WAN_INTERFACE"]
    result = {
        "connected": False,
        "ssid": None,
        "ip": None,
        "signal": None,
        "interface": wan,
    }
    try:
        r = _run(["nmcli", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "dev", "show", wan])
        for line in r.stdout.splitlines():
            if "GENERAL.CONNECTION" in line:
                ssid = line.split(":", 1)[-1].strip()
                if ssid and ssid != "--":
                    result["ssid"] = ssid
                    result["connected"] = True

        if result["connected"]:
            r2 = _run(["nmcli", "-f", "IP4.ADDRESS", "dev", "show", wan])
            for line in r2.stdout.splitlines():
                if "IP4.ADDRESS" in line:
                    result["ip"] = line.split(":", 1)[-1].strip().split("/")[0]

            r3 = _run(["nmcli", "--terse", "--escape", "no",
                       "-f", "SSID,SIGNAL,ACTIVE", "dev", "wifi", "list"])
            for line in r3.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) == 3 and parts[0] == result["ssid"] and parts[2].strip() == "yes":
                    result["signal"] = int(parts[1]) if parts[1].isdigit() else None
                    break
    except Exception as e:
        current_app.logger.error("get_current_connection error: %s", e)
    return result


def connect(ssid: str, password: str, bssid: Optional[str] = None) -> tuple[bool, str]:
    """Connect to a WiFi network via nmcli."""
    wan = current_app.config["WAN_INTERFACE"]
    cmd = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", wan]
    if password:
        cmd += ["password", password]
    if bssid:
        cmd += ["bssid", bssid]
    try:
        r = _run(cmd, timeout=30)
        if r.returncode == 0:
            return True, "Connected successfully."
        return False, r.stderr.strip() or r.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Connection timed out."
    except Exception as e:
        return False, str(e)


def disconnect() -> tuple[bool, str]:
    """Disconnect wlan0."""
    wan = current_app.config["WAN_INTERFACE"]
    try:
        r = _run(["nmcli", "dev", "disconnect", wan])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def forget_network(ssid: str) -> tuple[bool, str]:
    """Delete a saved NM connection by SSID."""
    try:
        r = _run(["nmcli", "connection", "delete", ssid])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def set_nm_priority(ssid: str, priority: int) -> bool:
    """Set NetworkManager autoconnect priority for a saved connection."""
    try:
        r = _run(["nmcli", "connection", "modify", ssid,
                  "connection.autoconnect-priority", str(priority)])
        return r.returncode == 0
    except Exception:
        return False


def sync_priorities(networks) -> None:
    """Push all network priorities from DB into NetworkManager."""
    for net in networks:
        set_nm_priority(net.ssid, net.priority)


def get_nm_saved_connections() -> list[str]:
    """Return list of saved NM WiFi connection names."""
    try:
        r = _run(["nmcli", "--terse", "-f", "NAME,TYPE", "connection", "show"])
        return [
            line.split(":")[0]
            for line in r.stdout.splitlines()
            if ":wifi" in line
        ]
    except Exception:
        return []
