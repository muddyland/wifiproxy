#!/bin/bash
# WiFi Proxy – install script
# Supports Raspberry Pi OS Trixie (Debian 13) and Bookworm (Debian 12).
# Must be run as root: sudo bash install.sh
#
# Flags (set as env vars):
#   APP_ONLY=1    Skip all network setup (NM, dnsmasq, iptables).
#                 Use when the bridge is already configured.
#   FORCE=1       Skip the Raspberry Pi hardware check.
#   REINSTALL=1   Re-generate SECRET_KEY and overwrite the systemd unit.
#                 (Default on a fresh install; not set on upgrades.)

set -euo pipefail

# ── Configuration (override via env) ───────────────────────────────────────
APP_DIR="${APP_DIR:-/opt/wifiproxy}"
APP_USER="${APP_USER:-wifiproxy}"
APP_PORT="${APP_PORT:-80}"
WAN_IF="${WAN_IF:-wlan0}"
LAN_IF="${LAN_IF:-eth0}"
LAN_IP="${LAN_IP:-192.168.50.1}"
LAN_PREFIX="${LAN_PREFIX:-24}"
NM_CONN="${NM_CONN:-Ethernet-Share}"
DHCP_RANGE_START="${DHCP_RANGE_START:-192.168.50.100}"
DHCP_RANGE_END="${DHCP_RANGE_END:-192.168.50.200}"

APP_ONLY="${APP_ONLY:-0}"   # set to 1 to skip network configuration
FORCE="${FORCE:-0}"
REINSTALL="${REINSTALL:-0}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[WiFi Proxy]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
skip()    { echo -e "${CYAN}[SKIP]${NC} $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

[[ $EUID -ne 0 ]] && die "Run as root: sudo bash install.sh"

# ── Check for Raspberry Pi ──────────────────────────────────────────────────
_is_pi=0
grep -qi "raspberry" /proc/cpuinfo 2>/dev/null && _is_pi=1
[[ -f /sys/firmware/devicetree/base/model ]] && \
    grep -qi "raspberry" /sys/firmware/devicetree/base/model 2>/dev/null && _is_pi=1

if [[ $_is_pi -eq 0 && "$FORCE" != "1" ]]; then
    warn "This does not appear to be a Raspberry Pi."
    warn "Run with FORCE=1 to install anyway: sudo FORCE=1 bash install.sh"
    exit 1
fi

# Detect if this is an upgrade (app already installed)
_upgrading=0
[[ -d "$APP_DIR" ]] && _upgrading=1

if [[ $_upgrading -eq 1 ]]; then
    info "Existing installation detected at $APP_DIR — upgrading."
else
    info "Fresh installation."
fi

echo ""
echo -e "  App directory : ${CYAN}$APP_DIR${NC}"
echo -e "  Run as user   : ${CYAN}$APP_USER${NC}"
echo -e "  Bind address  : ${CYAN}$LAN_IP:$APP_PORT${NC}"
if [[ "$APP_ONLY" == "1" ]]; then
    echo -e "  Network setup : ${YELLOW}SKIPPED (APP_ONLY=1)${NC}"
else
    echo -e "  WAN interface : ${CYAN}$WAN_IF${NC}"
    echo -e "  LAN interface : ${CYAN}$LAN_IF ($LAN_IP/$LAN_PREFIX)${NC}"
fi
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
PKGS=(python3 python3-venv python3-pip rsync git)

if [[ "$APP_ONLY" != "1" ]]; then
    PKGS+=(dnsmasq iptables iptables-persistent netfilter-persistent)
fi

apt-get install -y -qq "${PKGS[@]}"

# Trixie: force iptables legacy backend so iptables-persistent works correctly
if [[ "$APP_ONLY" != "1" ]] && update-alternatives --list iptables &>/dev/null; then
    if [[ -e /usr/sbin/iptables-legacy ]]; then
        update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
        update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
        info "iptables set to legacy backend."
    fi
fi

# ── 2. Create app user ──────────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    info "Creating system user: $APP_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
else
    skip "User $APP_USER already exists."
fi

# ── 3. Deploy app files ─────────────────────────────────────────────────────
info "Deploying app files to $APP_DIR..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$_upgrading" == "1" ]]; then
    rsync -a --exclude='venv/' --exclude='*.db' --exclude='__pycache__/' \
          --exclude='.env' "$SCRIPT_DIR/" "$APP_DIR/"
else
    rsync -a "$SCRIPT_DIR/" "$APP_DIR/"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"

# ── 4. Python virtual environment ───────────────────────────────────────────
info "Setting up Python virtual environment..."
if [[ ! -d "$APP_DIR/venv" ]]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/venv"

# ── 5. Secret key ───────────────────────────────────────────────────────────
# Preserve existing key on upgrades unless REINSTALL=1
EXISTING_KEY=""
if [[ -f /etc/systemd/system/wifiproxy.service ]]; then
    EXISTING_KEY=$(grep -oP '(?<=SECRET_KEY=).*' /etc/systemd/system/wifiproxy.service | tr -d '"' || true)
fi

if [[ -n "$EXISTING_KEY" && "$REINSTALL" != "1" ]]; then
    SECRET_KEY="$EXISTING_KEY"
    skip "Preserving existing SECRET_KEY."
else
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    info "Generated new SECRET_KEY."
fi

# ── 6. Network: NM static IP ────────────────────────────────────────────────
if [[ "$APP_ONLY" == "1" ]]; then
    skip "Network configuration skipped (APP_ONLY=1)."
else
    if nmcli connection show "$NM_CONN" &>/dev/null; then
        skip "NetworkManager connection '$NM_CONN' already exists — not modifying."
    else
        info "Configuring $LAN_IF static IP ($LAN_IP/$LAN_PREFIX) via NetworkManager..."
        nmcli connection delete "Wired connection 1" 2>/dev/null || true
        nmcli connection add type ethernet ifname "$LAN_IF" con-name "$NM_CONN" \
            ipv4.method manual \
            ipv4.addresses "$LAN_IP/$LAN_PREFIX" \
            ipv4.never-default yes \
            connection.autoconnect yes
        nmcli connection up "$NM_CONN" 2>/dev/null || true
    fi

    # ── 7. dnsmasq ──────────────────────────────────────────────────────────
    if [[ -f /etc/dnsmasq.conf ]] && grep -q "dhcp-range" /etc/dnsmasq.conf 2>/dev/null; then
        skip "dnsmasq already configured — not overwriting /etc/dnsmasq.conf."
        skip "Edit via the web UI or manually, then: systemctl restart dnsmasq"
    else
        info "Writing /etc/dnsmasq.conf..."
        systemctl stop dnsmasq 2>/dev/null || true
        cat > /etc/dnsmasq.conf <<EOF
interface=${LAN_IF}
bind-interfaces
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},255.255.255.0,24h
dhcp-option=option:router,${LAN_IP}
dhcp-option=option:dns-server,8.8.8.8,8.8.4.4
dhcp-leasefile=/var/lib/dnsmasq/dnsmasq.leases
EOF
    fi

    mkdir -p /var/lib/dnsmasq
    if getent group dnsmasq &>/dev/null; then
        chown dnsmasq:dnsmasq /var/lib/dnsmasq
    else
        chown dnsmasq:nogroup /var/lib/dnsmasq 2>/dev/null || true
    fi

    systemctl enable dnsmasq
    systemctl restart dnsmasq

    # ── 8. IP forwarding ────────────────────────────────────────────────────
    if [[ "$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null)" == "1" ]]; then
        skip "IP forwarding already enabled."
    else
        info "Enabling IP forwarding..."
    fi
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wifiproxy.conf
    sysctl -p /etc/sysctl.d/99-wifiproxy.conf -q

    # ── 9. iptables NAT ─────────────────────────────────────────────────────
    if iptables -t nat -L POSTROUTING -n 2>/dev/null | grep -q "MASQUERADE"; then
        skip "iptables MASQUERADE rule already present — not modifying."
        skip "Use the web UI → DHCP/Bridge → Re-apply NAT if you need to reset rules."
    else
        info "Configuring iptables NAT ($LAN_IF → $WAN_IF)..."
        iptables -t nat -F
        iptables -F FORWARD
        iptables -t nat -A POSTROUTING -o "$WAN_IF" -j MASQUERADE
        iptables -A FORWARD -i "$LAN_IF" -o "$WAN_IF" -j ACCEPT
        iptables -A FORWARD -i "$WAN_IF" -o "$LAN_IF" -m state \
            --state RELATED,ESTABLISHED -j ACCEPT
        netfilter-persistent save
        systemctl enable netfilter-persistent
    fi
fi  # end APP_ONLY check

# ── 10. Sudoers ─────────────────────────────────────────────────────────────
info "Installing sudoers rules..."
SUDOERS_SRC="$APP_DIR/sudoers.d/wifiproxy"
SUDOERS_DEST="/etc/sudoers.d/wifiproxy"

sed "s/www-data/${APP_USER}/g" "$SUDOERS_SRC" > "$SUDOERS_DEST"
chmod 440 "$SUDOERS_DEST"
if ! visudo -c -f "$SUDOERS_DEST" &>/dev/null; then
    rm -f "$SUDOERS_DEST"
    die "Sudoers syntax check failed. Check $SUDOERS_SRC."
fi

# ── 11. systemd service ─────────────────────────────────────────────────────
info "Installing systemd service..."
cat > /etc/systemd/system/wifiproxy.service <<EOF
[Unit]
Description=WiFi Proxy Web UI
After=network-online.target dnsmasq.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="BIND_HOST=${LAN_IP}"
Environment="PORT=${APP_PORT}"
Environment="SECRET_KEY=${SECRET_KEY}"
ExecStart=${APP_DIR}/venv/bin/python run.py
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable wifiproxy
systemctl restart wifiproxy

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
if [[ "$_upgrading" == "1" ]]; then
echo -e "${GREEN}║        WiFi Proxy upgraded successfully!         ║${NC}"
else
echo -e "${GREEN}║        WiFi Proxy installed successfully!        ║${NC}"
fi
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  URL:      http://${LAN_IP}                   ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  Username: admin                              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  Password: admin  (CHANGE THIS IMMEDIATELY)  ${GREEN}║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  Connect a device to eth0, then open         ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  the URL above in a browser.                 ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Service status : ${YELLOW}systemctl status wifiproxy${NC}"
echo -e "  Logs           : ${YELLOW}journalctl -u wifiproxy -f${NC}"
echo ""
