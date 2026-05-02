import subprocess
from datetime import datetime, timezone
from pathlib import Path
import psutil


def _sudo(cmd: list, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo"] + cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )


def get_quick_info() -> dict:
    """Lightweight stats for the dashboard."""
    try:
        return {
            "hostname": _get_hostname(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
        }
    except Exception:
        return {}


def get_full_info() -> dict:
    """Full system info for the system page."""
    try:
        boot = psutil.boot_time()
        uptime_seconds = (datetime.now(timezone.utc).timestamp()) - boot
        hours, rem = divmod(int(uptime_seconds), 3600)
        minutes = rem // 60

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu_temp = _get_cpu_temp()

        return {
            "hostname": _get_hostname(),
            "uptime": f"{hours}h {minutes}m",
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "cpu_temp": cpu_temp,
            "memory_total_mb": mem.total // (1024 * 1024),
            "memory_used_mb": mem.used // (1024 * 1024),
            "memory_percent": mem.percent,
            "disk_total_gb": disk.total // (1024 ** 3),
            "disk_used_gb": disk.used // (1024 ** 3),
            "disk_percent": disk.percent,
        }
    except Exception:
        return {}


def _get_hostname() -> str:
    try:
        return subprocess.run(
            ["hostname"], capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _get_cpu_temp() -> str | None:
    """Read CPU temp from Pi thermal zone."""
    try:
        temp = int(
            subprocess.run(
                ["cat", "/sys/class/thermal/thermal_zone0/temp"],
                capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip()
        ) / 1000
        return f"{temp:.1f}"
    except Exception:
        return None


def set_hostname(name: str) -> tuple[bool, str]:
    r = _sudo(["hostnamectl", "set-hostname", name])
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    _sync_hosts_hostname(name)
    return True, f"Hostname set to {name}."


def _sync_hosts_hostname(name: str) -> None:
    """Keep /etc/hosts in sync so sudo doesn't warn 'unable to resolve host <name>'.

    name must already be validated by validate_hostname() — it must match
    [a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9] with no slashes or shell-special chars,
    which is enforced here defensively before building the sed expression.
    """
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-]{0,61}[a-zA-Z0-9]?$', name):
        return  # refuse to touch /etc/hosts with an unexpected name
    has_line = subprocess.run(
        ["grep", "-q", r"^127\.0\.1\.1", "/etc/hosts"],
        capture_output=True,
    ).returncode == 0
    if has_line:
        _sudo(["sed", "-i", rf"s/^127\.0\.1\.1\b.*/127.0.1.1\t{name}/", "/etc/hosts"])
    else:
        subprocess.run(
            ["sudo", "tee", "-a", "/etc/hosts"],
            input=f"\n127.0.1.1\t{name}\n",
            capture_output=True, text=True, encoding="utf-8",
        )


def get_logs(lines: int = 100, unit: str = "") -> str:
    cmd = ["journalctl", "-n", str(lines), "--no-pager", "-o", "short-iso"]
    if unit:
        cmd += ["-u", unit]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        # Fall back to sudo — wifiproxy user may lack systemd-journal group access
        r2 = _sudo(cmd, timeout=10)
        return r2.stdout or r.stderr or ""
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def check_updates() -> str:
    """Return apt upgrade simulation output."""
    try:
        subprocess.run(["sudo", "apt-get", "update", "-qq"], capture_output=True, timeout=60)
        r = subprocess.run(
            ["apt-get", "--simulate", "upgrade"],
            capture_output=True, text=True, timeout=30
        )
        lines = [l for l in r.stdout.splitlines() if l.startswith("Inst ")]
        return f"{len(lines)} package(s) can be upgraded."
    except Exception as e:
        return str(e)


def run_update() -> tuple[bool, str]:
    try:
        r = _sudo(["apt-get", "update", "-qq"], timeout=120)
        if r.returncode != 0:
            return False, r.stderr.strip()
        r2 = _sudo(["apt-get", "upgrade", "-y", "-q"], timeout=300)
        return r2.returncode == 0, (r2.stderr or r2.stdout or "Update complete.").strip()
    except subprocess.TimeoutExpired:
        return False, "Update timed out — may still be running in background."
    except Exception as e:
        return False, str(e)


def reboot() -> tuple[bool, str]:
    try:
        _sudo(["systemctl", "reboot"])
        return True, "Rebooting..."
    except Exception as e:
        return False, str(e)


def shutdown() -> tuple[bool, str]:
    try:
        _sudo(["systemctl", "poweroff"])
        return True, "Shutting down..."
    except Exception as e:
        return False, str(e)


def dig_lookup(domain: str, record_type: str = "A", server: str = "") -> dict:
    cmd = ["dig", "+noall", "+answer", "+authority", "+question", domain, record_type]
    if server:
        cmd.insert(1, f"@{server}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=10)
        output = r.stdout or r.stderr or "(no output)"
        return {"output": output, "returncode": r.returncode}
    except subprocess.TimeoutExpired:
        return {"output": "dig timed out after 10 seconds.", "returncode": 1}
    except FileNotFoundError:
        return {"output": "dig not found — install dnsutils: sudo apt-get install dnsutils", "returncode": 1}
    except Exception as exc:
        return {"output": str(exc), "returncode": 1}


def get_host_dns() -> tuple[str, str]:
    """Return the first two nameservers from /etc/resolv.conf."""
    try:
        servers = []
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("nameserver") and len(line.split()) >= 2:
                servers.append(line.split()[1])
        return (servers[0] if servers else ""), (servers[1] if len(servers) > 1 else "")
    except Exception:
        return "", ""


def set_host_dns(dns1: str, dns2: str) -> tuple[bool, str]:
    """Overwrite /etc/resolv.conf with the given nameservers."""
    lines = [f"nameserver {dns1}"]
    if dns2:
        lines.append(f"nameserver {dns2}")
    content = "\n".join(lines) + "\n"
    try:
        r = subprocess.run(
            ["sudo", "tee", "/etc/resolv.conf"],
            input=content, capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            return False, r.stderr.strip()
        return True, "Host DNS servers updated."
    except Exception as exc:
        return False, str(exc)


_MONITORED_SERVICES = ["wifiproxy", "dnsmasq", "NetworkManager", "netfilter-persistent", "tailscaled"]


def get_service_statuses() -> list[dict]:
    results = []
    for svc in _MONITORED_SERVICES:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True, text=True, encoding="utf-8", timeout=5
            )
            state = r.stdout.strip()
        except Exception:
            state = "unknown"
        results.append({"name": svc, "state": state, "active": state == "active"})
    return results
