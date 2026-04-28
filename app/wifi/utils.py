import subprocess
import uuid
from typing import Optional
from flask import current_app


def _run(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def _sudo(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(["sudo"] + cmd, timeout=timeout)


def _sudo_write(path: str, content: str) -> subprocess.CompletedProcess:
    """Write content to a root-owned file via stdin, keeping content out of argv."""
    return subprocess.run(
        ["sudo", "tee", path],
        input=content, capture_output=True, text=True, encoding="utf-8", timeout=10,
    )


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


def _delete_nm_profile_for_ssid(ssid: str) -> None:
    """Delete any NM wifi connection whose SSID matches, regardless of profile name.

    nmcli list mode doesn't populate 802-11-wireless.ssid, so we get each
    wifi profile's SSID via an individual 'connection show <name>' query.
    Also tries a direct delete-by-name first as the fast path.
    """
    # Fast path: profile name usually equals the SSID
    _sudo(["nmcli", "connection", "delete", ssid])

    # Slow path: find profiles whose connection name differs from the SSID
    try:
        r = _sudo(["nmcli", "--terse", "-f", "NAME,TYPE", "connection", "show"])
        for line in r.stdout.splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) != 2 or "wireless" not in parts[1]:
                continue
            name = parts[0]
            if name == ssid:
                continue  # already deleted above
            r2 = _sudo(["nmcli", "--terse", "--escape", "no",
                        "-f", "802-11-wireless.ssid", "connection", "show", name])
            if r2.stdout.strip() == ssid:
                _sudo(["nmcli", "connection", "delete", name])
    except Exception:
        pass


def _build_nm_keyfile(ssid: str, password: str, iface: str, bssid: Optional[str]) -> str:
    """Build a NetworkManager keyfile profile. Password stays in file content, not argv."""
    conn_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"wifiproxy.{ssid}"))
    lines = [
        "[connection]",
        f"id={ssid}",
        f"uuid={conn_uuid}",
        "type=wifi",
        f"interface-name={iface}",
        "",
        "[wifi]",
        "mode=infrastructure",
        f"ssid={ssid}",
    ]
    if bssid:
        lines.append(f"bssid={bssid}")
    if password:
        lines += [
            "",
            "[wifi-security]",
            "auth-alg=open",
            "key-mgmt=wpa-psk",
            f"psk={password}",
        ]
    lines += [
        "",
        "[ipv4]",
        "method=auto",
        "",
        "[ipv6]",
        "method=auto",
        "addr-gen-mode=stable-privacy",
    ]
    return "\n".join(lines) + "\n"


def connect(ssid: str, password: str, bssid: Optional[str] = None) -> tuple[bool, str]:
    """Connect to a WiFi network.

    Writes an NM keyfile via stdin so the password never appears in argv
    (sudo logs the full command line, which would expose plaintext passwords).
    Any existing NM profile for this SSID is removed first.
    """
    wan = current_app.config["WAN_INTERFACE"]
    try:
        _delete_nm_profile_for_ssid(ssid)

        conn_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"wifiproxy.{ssid}"))
        profile_path = f"/etc/NetworkManager/system-connections/{conn_uuid}.nmconnection"
        keyfile = _build_nm_keyfile(ssid, password, wan, bssid)

        r = _sudo_write(profile_path, keyfile)
        if r.returncode != 0:
            return False, "Failed to write connection profile."

        _sudo(["chmod", "600", profile_path], timeout=5)
        _sudo(["nmcli", "connection", "reload"], timeout=10)

        r = _sudo(["nmcli", "connection", "up", ssid, "ifname", wan], timeout=30)
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
        r = _sudo(["nmcli", "dev", "disconnect", wan])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def forget_network(ssid: str) -> tuple[bool, str]:
    """Delete a saved NM connection by SSID."""
    try:
        r = _sudo(["nmcli", "connection", "delete", ssid])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def set_nm_priority(ssid: str, priority: int) -> bool:
    """Set NetworkManager autoconnect priority for a saved connection."""
    try:
        r = _sudo(["nmcli", "connection", "modify", ssid,
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
