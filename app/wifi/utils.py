import subprocess
from typing import Optional
from flask import current_app

_KEY_MGMT_ERROR = "key-mgmt"


def _run(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def _sudo(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(["sudo"] + cmd, timeout=timeout)


def _flush_entry(entry: dict, networks: list, seen: set) -> None:
    ssid = entry.get("ssid", "")
    if ssid and ssid not in seen:
        seen.add(ssid)
        networks.append(entry)


def scan_networks(rescan: bool = True) -> list[dict]:
    """Return visible WiFi networks sorted by signal strength.

    Uses nmcli multiline output to avoid colon-in-SSID parsing ambiguity.
    The parser flushes each entry when the next SSID line appears, so it
    works even if nmcli omits blank-line separators between entries.
    Pass rescan=False to use the cached scan result (faster, non-disruptive).

    A full channel sweep requires elevated NM permissions (PolicyKit).  The
    wifiproxy system user has no active session so NM silently skips the sweep
    for unprivileged callers and returns only the active BSSID.  We therefore
    run the rescan step under sudo; the cached listing step doesn't need it.
    """
    try:
        list_cmd = [
            "nmcli", "--mode", "multiline", "--escape", "no",
            "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
            "dev", "wifi", "list",
        ]
        if rescan:
            # --rescan yes blocks until the sweep completes before returning
            # results.  Run under sudo so NM grants authority for a full
            # multi-channel scan (system users have no PolicyKit session).
            list_cmd += ["--rescan", "yes"]
            result = _sudo(list_cmd, timeout=30)
        else:
            result = _run(list_cmd, timeout=15)
        networks: list[dict] = []
        seen: set[str] = set()
        entry: dict = {}
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "SSID":
                # Starting a new AP entry — flush the previous one first
                _flush_entry(entry, networks, seen)
                entry = {"ssid": val}
            elif key == "SIGNAL":
                entry["signal"] = int(val) if val.isdigit() else 0
            elif key == "SECURITY":
                entry["security"] = val if val and val != "--" else "Open"
            elif key == "ACTIVE":
                entry["active"] = val == "yes"
        _flush_entry(entry, networks, seen)
        return sorted(networks, key=lambda x: x.get("signal", 0), reverse=True)
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
    """Connect to a WiFi network via nmcli.

    If the existing NM connection profile is malformed (missing key-mgmt),
    delete it and retry so nmcli creates a fresh, correct profile.
    """
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
        error = r.stderr.strip() or r.stdout.strip()
        if _KEY_MGMT_ERROR in error:
            # Malformed profile — delete (needs sudo; system user has no polkit session)
            # and let nmcli create a clean one on retry.
            current_app.logger.warning(
                "key-mgmt error for '%s', deleting profile and retrying", ssid)

            _sudo(["nmcli", "connection", "delete", ssid])
            r2 = _run(cmd, timeout=30)
            if r2.returncode == 0:
                return True, "Connected successfully."
            return False, r2.stderr.strip() or r2.stdout.strip()
        return False, error
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


def get_nm_only_connections(db_ssids: set) -> list[str]:
    """Return NM WiFi connections that are not yet saved in the app DB."""
    return [s for s in get_nm_saved_connections() if s not in db_ssids]
