import re
import shutil
import subprocess
from pathlib import Path
from flask import current_app

WG_DIR = Path("/etc/wireguard")


def _sudo(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo"] + cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )


def is_installed() -> bool:
    return shutil.which("wg-quick") is not None


def get_active_interfaces() -> set[str]:
    try:
        r = subprocess.run(
            ["ip", "link", "show", "type", "wireguard"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        return set(re.findall(r"^\d+:\s+([^:@]+)", r.stdout, re.MULTILINE))
    except Exception:
        return set()


def is_autostart(name: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-enabled", f"wg-quick@{name}"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        return r.stdout.strip() == "enabled"
    except Exception:
        return False


def get_tunnels() -> list[dict]:
    tunnels = []
    if not is_installed():
        return tunnels
    try:
        active = get_active_interfaces()
        for conf in sorted(WG_DIR.glob("*.conf")):
            name = conf.stem
            tunnels.append({
                "name": name,
                "active": name in active,
                "autostart": is_autostart(name),
            })
    except Exception as exc:
        current_app.logger.error("WireGuard get_tunnels: %s", exc)
    return tunnels


def get_stats(name: str) -> str:
    try:
        r = _sudo(["wg", "show", name])
        return (r.stdout or r.stderr).strip()
    except Exception as exc:
        return str(exc)


def connect(name: str) -> tuple[bool, str]:
    try:
        r = _sudo(["wg-quick", "up", name], timeout=30)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "wg-quick up timed out."
    except Exception as exc:
        return False, str(exc)


def disconnect(name: str) -> tuple[bool, str]:
    try:
        r = _sudo(["wg-quick", "down", name], timeout=30)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "wg-quick down timed out."
    except Exception as exc:
        return False, str(exc)


def set_autostart(name: str, enable: bool) -> tuple[bool, str]:
    action = "enable" if enable else "disable"
    try:
        r = _sudo(["systemctl", action, f"wg-quick@{name}"])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as exc:
        return False, str(exc)


def save_config(name: str, content: str) -> tuple[bool, str]:
    conf_path = WG_DIR / f"{name}.conf"
    try:
        r = subprocess.run(
            ["sudo", "tee", str(conf_path)],
            input=content, capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            return False, r.stderr.strip()
        _sudo(["chmod", "600", str(conf_path)])
        return True, f"Config saved as {name}.conf"
    except Exception as exc:
        return False, str(exc)


def delete(name: str) -> tuple[bool, str]:
    if name in get_active_interfaces():
        disconnect(name)
    conf_path = WG_DIR / f"{name}.conf"
    try:
        r = _sudo(["rm", str(conf_path)])
        return r.returncode == 0, f"Deleted {name}." if r.returncode == 0 else r.stderr.strip()
    except Exception as exc:
        return False, str(exc)
