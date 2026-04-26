import subprocess
from datetime import datetime, timezone
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
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def get_logs(lines: int = 100) -> str:
    try:
        r = subprocess.run(
            ["journalctl", "-n", str(lines), "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return r.stdout
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
