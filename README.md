# WiFi Bridge Manager

A Flask web UI for managing a Raspberry Pi configured as a WiFi-to-Ethernet bridge. Lets you manage upstream WiFi connections, DHCP/NAT, Tailscale (including headscale), and general Pi administration — all from a browser on your local network.

## Features

- **Secure authentication** — single admin account, bcrypt-hashed password, CSRF protection, rate-limited login, session hardening
- **WiFi management** — scan networks, save profiles with priority tiers, drag-to-reorder, connect/disconnect, BSSID locking, hidden network support; syncs priorities into NetworkManager
- **DHCP / bridge** — edit dnsmasq config (range, gateway, DNS, lease time), view active leases, re-apply iptables NAT rules
- **Tailscale** — supports custom login servers (headscale), auth keys, exit-node advertising, route advertising, interactive browser-auth flow
- **System** — hostname, CPU/memory/disk/temp stats, apt updates, reboot/shutdown, journal log viewer, admin password change
- **Security** — LAN-only binding (management UI unreachable from upstream WiFi), security headers (CSP, X-Frame-Options, etc.), input validation against injection on all subprocess calls

## Architecture

```
wlan0  ──── upstream WiFi (WAN)
eth0   ──── 192.168.50.1/24, dnsmasq DHCP, iptables NAT → wlan0
```

The web app binds to `192.168.50.1:80` by default so it is only reachable from devices connected to the LAN side.

## Requirements

- Raspberry Pi OS (or Debian-based) with NetworkManager active
- `dnsmasq`, `iptables-persistent` installed (handled by the original setup script)
- `tailscale` binary (optional — only needed for Tailscale features)
- Python 3.11+

## Installation

### 1. Clone and set up the venv

```bash
git clone <repo> /opt/wifiproxy
cd /opt/wifiproxy
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Set a strong secret key

```bash
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

Or edit `wifiproxy.service` and set it there permanently.

### 3. Configure sudoers

```bash
sudo cp sudoers.d/wifiproxy /etc/sudoers.d/wifiproxy
sudo chmod 440 /etc/sudoers.d/wifiproxy
sudo visudo -c   # verify syntax before trusting it
```

Edit the file to replace `www-data` with whichever user will run the app if different.

### 4. Install and start the systemd service

```bash
sudo cp wifiproxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wifiproxy
```

### 5. Change the default password

Open `http://192.168.50.1` in a browser, log in with **admin / admin**, then go to **System → Change Admin Password** immediately.

## Development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
BIND_HOST=127.0.0.1 PORT=5000 SECRET_KEY=dev venv/bin/python run.py
```

Run tests:

```bash
venv/bin/pip install pytest
venv/bin/pytest
```

## Security notes

- The app binds to `192.168.50.1` (eth0) only — never to `wlan0`. Traffic from the upstream WiFi network cannot reach the management UI.
- All subprocess calls use list arguments (no `shell=True`), preventing shell injection.
- All user inputs that flow into subprocess commands are validated through `app/validators.py` before use.
- Passwords (WiFi, Tailscale auth keys) are encrypted at rest using Fernet symmetric encryption keyed from `SECRET_KEY`.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- Login is rate-limited to 10 attempts/minute, 30/hour per IP.

## File layout

```
app/
  auth/        login, logout, password change
  wifi/        network scan, save, connect, priority
  dhcp/        dnsmasq config, iptables, leases
  tailscale/   tailscale up/down/logout, headscale support
  system/      hostname, updates, reboot, logs
  validators.py  input validation for all subprocess-bound values
  crypto.py      Fernet encryption helpers
  models.py      SQLAlchemy models (SQLite)
  templates/     Jinja2 + Bootstrap 5 UI
tests/           pytest suite — 144 tests, all subprocess calls mocked
sudoers.d/wifiproxy   sudoers rules (copy to /etc/sudoers.d/)
wifiproxy.service     systemd unit file
```
