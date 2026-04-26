import subprocess
import json
import shutil
from flask import current_app


def _run(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo"] + cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )


def is_installed() -> bool:
    return shutil.which("tailscale") is not None


def get_status() -> dict:
    """Return parsed tailscale status."""
    result = {
        "installed": is_installed(),
        "running": False,
        "connected": False,
        "ip": None,
        "hostname": None,
        "peers": [],
        "exit_node_active": False,
        "login_server": None,
        "raw": None,
    }
    if not result["installed"]:
        return result

    try:
        r = _run(["tailscale", "status", "--json"])
        if r.returncode != 0:
            return result

        data = json.loads(r.stdout)
        result["raw"] = data
        result["running"] = True

        self_node = data.get("Self", {})
        result["ip"] = (self_node.get("TailscaleIPs") or [None])[0]
        result["hostname"] = self_node.get("HostName")
        result["login_server"] = data.get("CurrentTailnet", {}).get("MagicDNSSuffix")

        backend = data.get("BackendState", "")
        result["connected"] = backend == "Running"
        result["exit_node_active"] = bool(data.get("ExitNodeStatus"))

        peers = []
        for peer in data.get("Peer", {}).values():
            peers.append({
                "hostname": peer.get("HostName"),
                "ip": (peer.get("TailscaleIPs") or [None])[0],
                "online": peer.get("Online", False),
                "exit_node": peer.get("ExitNode", False),
            })
        result["peers"] = peers
    except (json.JSONDecodeError, Exception) as e:
        current_app.logger.error("tailscale status error: %s", e)

    return result


def login(login_server: str, auth_key: str = "", advertise_exit_node: bool = False,
          accept_routes: bool = False, advertise_routes: str = "") -> tuple[bool, str]:
    """Run tailscale up with given parameters. Returns (success, message_or_login_url)."""
    cmd = ["tailscale", "up", f"--login-server={login_server}", "--reset"]
    if auth_key:
        cmd.append(f"--authkey={auth_key}")
    if advertise_exit_node:
        cmd.append("--advertise-exit-node")
    if accept_routes:
        cmd.append("--accept-routes")
    if advertise_routes:
        cmd.append(f"--advertise-routes={advertise_routes}")

    try:
        r = _run(cmd, timeout=60)
        output = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            return True, "Connected to Tailscale."
        # Headscale / interactive login returns a URL
        for line in output.splitlines():
            if line.startswith("https://"):
                return False, line  # caller checks for URL
        return False, output
    except subprocess.TimeoutExpired:
        return False, "tailscale up timed out — check logs."
    except Exception as e:
        return False, str(e)


def down() -> tuple[bool, str]:
    try:
        r = _run(["tailscale", "down"])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def logout() -> tuple[bool, str]:
    try:
        r = _run(["tailscale", "logout"])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)
