import subprocess
from datetime import datetime, timezone
from pathlib import Path

WG_DIR = Path("/etc/wireguard")


def _sudo_read(path: str) -> str:
    try:
        r = subprocess.run(
            ["sudo", "cat", path],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _list_wg_conf_stems() -> list[str]:
    try:
        return [f.stem for f in sorted(WG_DIR.glob("*.conf"))]
    except PermissionError:
        try:
            r = subprocess.run(
                ["sudo", "ls", str(WG_DIR)],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            if r.returncode == 0:
                return [
                    Path(name).stem
                    for name in r.stdout.splitlines()
                    if name.endswith(".conf")
                ]
        except Exception:
            pass
        return []
    except Exception:
        return []


def is_fresh_install() -> bool:
    from app.models import User
    user = User.query.filter_by(username="admin").first()
    return user is not None and user.check_password("admin")


def export_backup() -> dict:
    from app.models import WifiNetwork, DhcpConfig, TailscaleConfig, DhcpReservation

    cfg = DhcpConfig.query.first()
    dhcp_config = {}
    if cfg:
        dhcp_config = {
            "lan_interface": cfg.lan_interface,
            "wan_interface": cfg.wan_interface,
            "gateway": cfg.gateway,
            "subnet_mask": cfg.subnet_mask,
            "dns1": cfg.dns1,
            "dns2": cfg.dns2,
            "range_start": cfg.range_start,
            "range_end": cfg.range_end,
            "lease_time": cfg.lease_time,
        }

    reservations = [
        {"mac": r.mac, "nickname": r.nickname, "static_ip": r.static_ip}
        for r in DhcpReservation.query.all()
    ]

    wifi_networks = [
        {
            "ssid": n.ssid,
            "password": n.password,
            "priority": n.priority,
            "bssid": n.bssid,
            "auto_connect": n.auto_connect,
            "hidden": n.hidden,
        }
        for n in WifiNetwork.query.all()
    ]

    ts = TailscaleConfig.query.first()
    tailscale_config = {}
    if ts:
        tailscale_config = {
            "login_server": ts.login_server,
            "auth_key": ts.auth_key,
            "advertise_exit_node": ts.advertise_exit_node,
            "accept_routes": ts.accept_routes,
            "accept_dns": ts.accept_dns,
            "advertise_routes": ts.advertise_routes,
        }

    wireguard_tunnels = []
    for stem in _list_wg_conf_stems():
        content = _sudo_read(str(WG_DIR / f"{stem}.conf"))
        if content:
            wireguard_tunnels.append({"name": stem, "config": content})

    hostname = _sudo_read("/etc/hostname").strip()

    return {
        "version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hostname": hostname,
        "data": {
            "dhcp_config": dhcp_config,
            "dhcp_reservations": reservations,
            "wifi_networks": wifi_networks,
            "tailscale_config": tailscale_config,
            "wireguard_tunnels": wireguard_tunnels,
        },
    }


def import_backup(data: dict) -> tuple[bool, str]:
    from app import db
    from app.models import WifiNetwork, DhcpConfig, TailscaleConfig, DhcpReservation
    from app.wireguard.utils import save_config as wg_save_config
    from app.validators import validate_tunnel_name, ValidationError

    if data.get("version") != "1":
        return False, "Unsupported backup version."

    backup_data = data.get("data", {})
    if not isinstance(backup_data, dict):
        return False, "Invalid backup structure."

    try:
        dhcp = backup_data.get("dhcp_config", {})
        if isinstance(dhcp, dict) and dhcp:
            cfg = DhcpConfig.query.first()
            if not cfg:
                cfg = DhcpConfig()
                db.session.add(cfg)
            for field in ("lan_interface", "wan_interface", "gateway", "subnet_mask",
                          "dns1", "dns2", "range_start", "range_end", "lease_time"):
                if field in dhcp and isinstance(dhcp[field], str):
                    setattr(cfg, field, dhcp[field])

        DhcpReservation.query.delete()
        for res in backup_data.get("dhcp_reservations", []):
            if not isinstance(res, dict):
                continue
            db.session.add(DhcpReservation(
                mac=str(res.get("mac", ""))[:17],
                nickname=str(res.get("nickname", ""))[:64],
                static_ip=str(res.get("static_ip", ""))[:15],
            ))

        WifiNetwork.query.delete()
        for net in backup_data.get("wifi_networks", []):
            if not isinstance(net, dict):
                continue
            n = WifiNetwork(
                ssid=str(net.get("ssid", ""))[:256],
                priority=int(net["priority"]) if isinstance(net.get("priority"), (int, float)) else 10,
                bssid=str(net["bssid"])[:17] if net.get("bssid") else None,
                auto_connect=bool(net.get("auto_connect", True)),
                hidden=bool(net.get("hidden", False)),
            )
            n.password = str(net.get("password", ""))
            db.session.add(n)

        ts_data = backup_data.get("tailscale_config", {})
        if isinstance(ts_data, dict) and ts_data:
            ts = TailscaleConfig.query.first()
            if not ts:
                ts = TailscaleConfig()
                db.session.add(ts)
            for field in ("login_server", "advertise_exit_node", "accept_routes",
                          "accept_dns", "advertise_routes"):
                if field in ts_data:
                    setattr(ts, field, ts_data[field])
            if ts_data.get("auth_key"):
                ts.auth_key = str(ts_data["auth_key"])

        db.session.commit()

        wg_errors = []
        for tunnel in backup_data.get("wireguard_tunnels", []):
            if not isinstance(tunnel, dict):
                continue
            name = str(tunnel.get("name", ""))
            config = str(tunnel.get("config", ""))
            if not name or not config:
                continue
            try:
                validate_tunnel_name(name)
            except ValidationError:
                wg_errors.append(name)
                continue
            ok, msg = wg_save_config(name, config)
            if not ok:
                wg_errors.append(name)

        if wg_errors:
            return True, f"Restored, but failed to write WireGuard configs: {', '.join(wg_errors)}."
        return True, "Backup restored successfully."

    except Exception as exc:
        db.session.rollback()
        return False, f"Restore failed: {exc}"
