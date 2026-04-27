# WiFi Bridge Manager

A Flask web UI for managing a Raspberry Pi configured as a WiFi-to-Ethernet bridge. Manage upstream WiFi connections, DHCP/NAT, Tailscale (including headscale), WireGuard VPN tunnels, and general Pi administration — all from a browser on your local network.

## Features

- **Secure authentication** — single admin account, bcrypt-hashed password, CSRF protection, rate-limited login, session hardening
- **WiFi management** — scan networks, save profiles with priority tiers, drag-to-reorder, connect/disconnect, BSSID locking, hidden network support; auto-switches to higher-priority networks via watchdog
- **DHCP / bridge** — edit dnsmasq config (range, gateway, DNS, lease time), view active leases with hostname nicknames, DHCP reservations (static IP per MAC), re-apply iptables NAT rules
- **Tailscale** — supports custom login servers (headscale), auth keys, exit-node advertising, route advertising, accept-DNS toggle, interactive browser-auth flow; exit node selection and clearing from the peers list
- **WireGuard** — upload `.conf` files, connect/disconnect tunnels, enable autostart via systemd, view live tunnel stats; configs stored in `/etc/wireguard/`
- **Dashboard** — real-time traffic graphs (LAN/WAN), service status card, active DHCP leases at a glance
- **System** — hostname, CPU/memory/disk/temp stats, apt updates, reboot/shutdown, journal log viewer, admin password change
- **Security** — LAN-only binding, security headers (CSP, X-Frame-Options, etc.), input validation against injection on all subprocess calls, encrypted credential storage
- **Dark/light mode** — auto-detects system preference, toggle persisted in localStorage

## Architecture

```
wlan0  ──── upstream WiFi (WAN)
eth0   ──── 192.168.50.1/24, dnsmasq DHCP, iptables NAT → wlan0
```

The web app binds to `192.168.50.1:80` by default so it is only reachable from devices connected to the LAN side.

## Requirements

- Raspberry Pi OS (or Debian-based) with NetworkManager active
- Python 3.11+
- The install script handles everything else (dnsmasq, iptables-persistent, WireGuard, Tailscale)

## Installation

```bash
git clone <repo> /tmp/wifiproxy
cd /tmp/wifiproxy
sudo bash install.sh
```

The script:
1. Installs system packages: dnsmasq, iptables-persistent, WireGuard tools, Tailscale
2. Creates a `wifiproxy` system user
3. Deploys the app to `/opt/wifiproxy`
4. Sets up the Python virtualenv and installs pip dependencies
5. Configures NetworkManager, dnsmasq, IP forwarding, and iptables NAT
6. Installs the sudoers rules and starts a gunicorn systemd service

**Upgrade (network already configured):**

```bash
git pull && sudo APP_ONLY=1 bash install.sh
```

### Install flags

| Variable | Default | Effect |
|----------|---------|--------|
| `APP_ONLY=1` | `0` | Skip network setup (NM, dnsmasq, iptables) — use on upgrades |
| `FORCE=1` | `0` | Skip the Raspberry Pi hardware check |
| `REINSTALL=1` | `0` | Re-generate `SECRET_KEY` and overwrite the systemd unit |
| `APP_DIR` | `/opt/wifiproxy` | Install path |
| `APP_USER` | `wifiproxy` | User that runs the service |
| `APP_PORT` | `80` | Bind port |
| `WAN_IF` | `wlan0` | Upstream (internet) interface |
| `LAN_IF` | `eth0` | LAN (bridge) interface |
| `LAN_IP` | `192.168.50.1` | LAN gateway IP |

### After install

1. Connect a device to the Pi's ethernet port
2. Open `http://192.168.50.1` in a browser
3. Log in with **admin / admin**
4. Go to **System → Change Admin Password** immediately

## Development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
BIND_HOST=127.0.0.1 PORT=5000 SECRET_KEY=dev venv/bin/python run.py
```

Run tests:

```bash
venv/bin/pytest
```

Or with verbose output:

```bash
venv/bin/pytest -v
```

## Security notes

- The app binds to `192.168.50.1` (eth0) only — never to `wlan0`. Traffic from the upstream WiFi network cannot reach the management UI.
- All subprocess calls use list arguments (no `shell=True`), preventing shell injection.
- All user inputs that flow into subprocess commands are validated through `app/validators.py` before use.
- Passwords, WiFi passphrases, and Tailscale auth keys are encrypted at rest using Fernet symmetric encryption keyed from `SECRET_KEY`.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- Login is rate-limited to 10 attempts/minute, 30/hour per IP.
- WireGuard configs are stored at `/etc/wireguard/<name>.conf` with mode 600.

## File layout

```
app/
  auth/        login, logout, password change
  wifi/        network scan, save, connect, priority, watchdog
  dhcp/        dnsmasq config, iptables, leases, reservations
  tailscale/   tailscale up/down/logout, exit node, headscale support
  wireguard/   tunnel upload, connect/disconnect, autostart, stats
  system/      hostname, updates, reboot, logs
  main/        dashboard, traffic API, service status API
  validators.py  input validation for all subprocess-bound values
  crypto.py      Fernet encryption helpers
  models.py      SQLAlchemy models (SQLite)
  templates/     Jinja2 + Bootstrap 5.3 UI (dark/light mode)
tests/           pytest suite — 223 tests, all subprocess calls mocked
sudoers.d/wifiproxy   sudoers rules (installed automatically)
install.sh            full install/upgrade script
```
