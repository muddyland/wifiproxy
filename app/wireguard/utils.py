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


def _get_lan_iface() -> str:
    """Read LAN interface from DhcpConfig; fall back to eth0."""
    try:
        from app.models import DhcpConfig
        cfg = DhcpConfig.query.first()
        return cfg.lan_interface if cfg else "eth0"
    except Exception:
        return "eth0"


def _apply_nat_rules(action: str, wg_iface: str, lan_iface: str) -> None:
    """Add (action='-A') or remove (action='-D') the three iptables rules that
    allow LAN clients to reach the internet through a WireGuard tunnel.

    wg-quick sets up policy routing so forwarded packets use wg0, but the
    FORWARD chain and NAT table still need explicit entries.
    """
    rule_specs = [
        # Masquerade LAN traffic leaving through the WireGuard interface
        ["-t", "nat", action, "POSTROUTING", "-o", wg_iface, "-j", "MASQUERADE"],
        # Allow forwarding from LAN into the tunnel
        [action, "FORWARD", "-i", lan_iface, "-o", wg_iface, "-j", "ACCEPT"],
        # Allow established/related traffic back from the tunnel to LAN
        [action, "FORWARD", "-i", wg_iface, "-o", lan_iface,
         "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
    ]
    for spec in rule_specs:
        if action == "-A":
            check = ["-C" if s == action else s for s in spec]
            r = subprocess.run(["sudo", "iptables"] + check, capture_output=True)
            if r.returncode == 0:
                continue  # rule already exists — skip to avoid duplicates
        subprocess.run(["sudo", "iptables"] + spec, capture_output=True)


def has_nat_rules(name: str) -> bool:
    """Return True if the MASQUERADE rule for this tunnel is in iptables."""
    try:
        r = subprocess.run(
            ["sudo", "iptables", "-t", "nat", "-C", "POSTROUTING",
             "-o", name, "-j", "MASQUERADE"],
            capture_output=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def get_tunnels() -> list[dict]:
    tunnels = []
    if not is_installed():
        return tunnels
    try:
        active = get_active_interfaces()
        try:
            conf_files = sorted(WG_DIR.glob("*.conf"))
        except PermissionError:
            current_app.logger.warning(
                "Cannot list /etc/wireguard (permission denied). "
                "Run: sudo chmod 755 /etc/wireguard"
            )
            for name in sorted(active):
                tunnels.append({
                    "name": name, "active": True,
                    "autostart": is_autostart(name),
                    "routing": has_nat_rules(name),
                })
            return tunnels
        for conf in conf_files:
            name = conf.stem
            active_now = name in active
            tunnels.append({
                "name": name,
                "active": active_now,
                "autostart": is_autostart(name),
                "routing": has_nat_rules(name) if active_now else False,
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
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()
        lan_iface = _get_lan_iface()
        _apply_nat_rules("-A", name, lan_iface)
        return True, f"Connected {name}. LAN traffic routing active."
    except subprocess.TimeoutExpired:
        return False, "wg-quick up timed out."
    except Exception as exc:
        return False, str(exc)


def disconnect(name: str) -> tuple[bool, str]:
    try:
        lan_iface = _get_lan_iface()
        _apply_nat_rules("-D", name, lan_iface)
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
            err = r.stderr.strip() or "Could not write config — check sudoers rules."
            return False, err
        _sudo(["chmod", "600", str(conf_path)])
        _sudo(["chmod", "755", str(WG_DIR)])
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
