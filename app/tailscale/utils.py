import subprocess
import json
import shutil
from flask import current_app


def _run(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run with sudo — used for mutating commands (up, down, logout)."""
    return subprocess.run(
        ["sudo"] + cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )


def _run_plain(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run without sudo — used for read-only queries (status)."""
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )


def is_installed() -> bool:
    return shutil.which("tailscale") is not None


def get_status() -> dict:
    """Return parsed tailscale status. Tries without sudo first."""
    result = {
        "installed": is_installed(),
        "running": False,
        "connected": False,
        "needs_auth": False,
        "auth_url": None,
        "ip": None,
        "hostname": None,
        "peers": [],
        "exit_node_active": False,
        "exit_node_ip": None,
        "login_server": None,
        "backend_state": None,
        "live_advertise_exit_node": None,
        "live_advertised_routes": None,
    }
    if not result["installed"]:
        return result

    try:
        # Status queries don't need root — try plain first, fall back to sudo.
        r = _run_plain(["tailscale", "status", "--json"])
        if r.returncode != 0:
            r = _run(["tailscale", "status", "--json"])

        # Attempt to parse even on non-zero exit: tailscale sometimes exits 1
        # while still returning valid JSON (e.g. NeedsLogin state).
        try:
            data = json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            current_app.logger.warning("tailscale status returned non-JSON: %s", r.stderr)
            return result

        result["running"] = True
        backend = data.get("BackendState", "")
        result["backend_state"] = backend
        result["connected"] = backend == "Running"
        result["needs_auth"] = backend in ("NeedsLogin", "NeedsMachineAuth", "NoState")

        # Auth URL is present when interactive login is required
        auth_url = data.get("AuthURL", "")
        if auth_url:
            result["auth_url"] = auth_url

        self_node = data.get("Self") or {}
        # IPs appear at top-level in newer builds and inside Self in older ones
        ips = data.get("TailscaleIPs") or self_node.get("TailscaleIPs") or []
        result["ip"] = ips[0] if ips else None
        result["hostname"] = self_node.get("HostName")
        result["login_server"] = (data.get("CurrentTailnet") or {}).get("MagicDNSSuffix")
        exit_node_status = data.get("ExitNodeStatus") or {}
        result["exit_node_active"] = bool(exit_node_status)
        result["exit_node_ip"] = (exit_node_status.get("TailscaleIPs") or [None])[0]

        # Live config flags — reflect what tailscale is actually running with
        result["live_advertise_exit_node"] = bool(self_node.get("ExitNodeOption"))
        primary_routes = self_node.get("PrimaryRoutes") or []
        result["live_advertised_routes"] = ", ".join(primary_routes)

        peers = []
        for peer in (data.get("Peer") or {}).values():
            peers.append({
                "hostname": peer.get("HostName"),
                "ip": ((peer.get("TailscaleIPs") or [None])[0]),
                "online": peer.get("Online", False),
                "exit_node": peer.get("ExitNode", False),
                "exit_node_option": peer.get("ExitNodeOption", False),
            })
        result["peers"] = peers

    except Exception as exc:
        current_app.logger.error("tailscale get_status error: %s", exc)

    return result


def get_prefs() -> dict:
    """Return selected tailscale prefs (ControlURL, RouteAll). Best-effort — may return {}."""
    try:
        r = _run_plain(["tailscale", "prefs", "--json"])
        if r.returncode != 0:
            r = _run(["tailscale", "prefs", "--json"])
        data = json.loads(r.stdout)
        return {
            "control_url": data.get("ControlURL"),
            "accept_routes": data.get("RouteAll"),
            "accept_dns": data.get("CorpDNS"),
        }
    except Exception:
        return {}


def set_exit_node(ip: str) -> tuple[bool, str]:
    try:
        r = _run(["tailscale", "set", f"--exit-node={ip}",
                  "--exit-node-allow-lan-access=true"])
        if r.returncode == 0:
            return True, f"Exit node set to {ip}."
        return False, (r.stderr or r.stdout).strip()
    except Exception as exc:
        return False, str(exc)


def clear_exit_node() -> tuple[bool, str]:
    try:
        r = _run(["tailscale", "set", "--exit-node=",
                  "--exit-node-allow-lan-access=false"])
        if r.returncode == 0:
            return True, "Exit node cleared."
        return False, (r.stderr or r.stdout).strip()
    except Exception as exc:
        return False, str(exc)


def login(login_server: str, auth_key: str = "", advertise_exit_node: bool = False,
          accept_routes: bool = False, advertise_routes: str = "",
          accept_dns: bool = True) -> tuple[bool, str]:
    """Run tailscale up. Returns (success, message_or_auth_url)."""
    cmd = ["tailscale", "up", f"--login-server={login_server}", "--reset"]
    if auth_key:
        cmd.append(f"--authkey={auth_key}")
    if advertise_exit_node:
        cmd.append("--advertise-exit-node")
    if accept_routes:
        cmd.append("--accept-routes")
    if not accept_dns:
        cmd.append("--accept-dns=false")
    if advertise_routes:
        cmd.append(f"--advertise-routes={advertise_routes}")

    try:
        r = _run(cmd, timeout=60)
        output = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            return True, "Connected to Tailscale."
        for line in output.splitlines():
            if line.startswith("https://"):
                return False, line
        return False, output
    except subprocess.TimeoutExpired:
        return False, "tailscale up timed out — check logs."
    except Exception as exc:
        return False, str(exc)


def down() -> tuple[bool, str]:
    try:
        r = _run(["tailscale", "down"])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as exc:
        return False, str(exc)


def logout() -> tuple[bool, str]:
    try:
        r = _run(["tailscale", "logout"])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as exc:
        return False, str(exc)
