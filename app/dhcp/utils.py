import subprocess
from pathlib import Path
from flask import current_app


def _sudo(cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo"] + cmd, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )


def get_bridge_status() -> dict:
    """Check whether IP forwarding and NAT are active."""
    status = {"forwarding": False, "nat_active": False, "dnsmasq_running": False}
    try:
        fwd = Path("/proc/sys/net/ipv4/ip_forward").read_text(encoding="utf-8").strip()
        status["forwarding"] = fwd == "1"

        r = _sudo(["iptables", "-t", "nat", "-L", "POSTROUTING", "-n"])
        status["nat_active"] = "MASQUERADE" in r.stdout

        r2 = subprocess.run(
            ["systemctl", "is-active", "dnsmasq"],
            capture_output=True, text=True, encoding="utf-8",
        )
        status["dnsmasq_running"] = r2.stdout.strip() == "active"
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("get_bridge_status error: %s", exc)
    return status


def get_leases() -> list[dict]:
    """Parse the dnsmasq leases file."""
    leases_path = current_app.config["DNSMASQ_LEASES"]
    leases: list[dict] = []
    try:
        content = Path(leases_path).read_text(encoding="utf-8")
        for line in content.strip().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                leases.append({
                    "expires": parts[0],
                    "mac": parts[1],
                    "ip": parts[2],
                    "hostname": parts[3] if parts[3] != "*" else "",
                })
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("get_leases error: %s", exc)
    return leases


def write_dnsmasq_config(cfg) -> tuple[bool, str]:
    """Write /etc/dnsmasq.conf based on the DhcpConfig model instance."""
    conf = (
        f"interface={cfg.lan_interface}\n"
        f"bind-interfaces\n"
        f"dhcp-range={cfg.range_start},{cfg.range_end},{cfg.subnet_mask},{cfg.lease_time}\n"
        f"dhcp-option=option:router,{cfg.gateway}\n"
        f"dhcp-option=option:dns-server,{cfg.dns1},{cfg.dns2}\n"
        f"dhcp-leasefile=/var/lib/dnsmasq/dnsmasq.leases\n"
    )
    conf_path = current_app.config["DNSMASQ_CONF"]
    try:
        r = subprocess.run(
            ["sudo", "tee", conf_path],
            input=conf, capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            return False, r.stderr.strip()
        r2 = _sudo(["systemctl", "restart", "dnsmasq"])
        if r2.returncode != 0:
            return False, r2.stderr.strip()
        return True, "dnsmasq configured and restarted."
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def update_lan_ip(connection_name: str, new_gateway: str) -> tuple[bool, str]:
    """Update the NM static IP on the LAN connection to match the new gateway."""
    try:
        r = subprocess.run(
            ["nmcli", "connection", "modify", connection_name,
             "ipv4.addresses", f"{new_gateway}/24"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            return False, r.stderr.strip()
        r2 = subprocess.run(
            ["nmcli", "connection", "up", connection_name],
            capture_output=True, text=True, encoding="utf-8",
        )
        return r2.returncode == 0, (r2.stderr or r2.stdout).strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def apply_iptables(wan: str, lan: str) -> tuple[bool, str]:
    """Re-apply NAT rules and save them."""
    cmds = [
        ["iptables", "-t", "nat", "-F"],
        ["iptables", "-F", "FORWARD"],
        ["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", wan, "-j", "MASQUERADE"],
        ["iptables", "-A", "FORWARD", "-i", lan, "-o", wan, "-j", "ACCEPT"],
        ["iptables", "-A", "FORWARD", "-i", wan, "-o", lan,
         "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
        ["netfilter-persistent", "save"],
    ]
    try:
        for cmd in cmds:
            r = _sudo(cmd)
            if r.returncode != 0:
                return False, f"Failed on '{' '.join(cmd)}': {r.stderr.strip()}"
        return True, "iptables rules applied and saved."
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
