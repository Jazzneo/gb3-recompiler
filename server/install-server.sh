#!/usr/bin/env bash
# Install the GB3 co-op server on a Linux machine that stays on: a free cloud VM, a home server,
# a spare PC. One command, from the unpacked Recompiler release (GB3-Recompiler-v*/):
#
#   sudo bash server/install-server.sh [--port 31313] [--key SECRET]
#   sudo bash server/install-server.sh --uninstall
#
# What it does: copies the server (self-contained: its own glibc and Qt) to /opt/gb3-server, makes a
# system user gb3server with its data in /var/lib/gb3-server, starts it as the systemd service
# gb3-server (also at every boot) and opens its ports in the machine's firewall (ufw, firewalld or
# plain iptables). A cloud provider's own firewall ("security list", "security group") still has to
# allow the same ports: see server/README.md.
#
# Ports: TCP 31313 (accounts, rooms), UDP 31314 (signaling), TCP 31315 (web API), UDP 3478 (relay
# for players whose routers block direct play). With --port P they are P, P+1, P+2 and 3478.
# --key: only players who type this key in the Recompiler's Network window can create an account.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd -P)
top=$(dirname "$here")
port=31313 key='' uninstall=0
while (($#)); do
    case $1 in
        --port) port=$2; shift ;;
        --key) key=$2; shift ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
[[ $EUID -eq 0 ]] || { echo "run it with sudo" >&2; exit 1; }
[[ $port =~ ^[0-9]+$ ]] && ((port > 0 && port < 65534)) || { echo "bad --port" >&2; exit 2; }

ports_tcp="$port $((port + 2))" ports_udp="$((port + 1)) 3478"

firewall() {   # $1 = add | remove
    local p
    if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q 'Status: active'; then
        for p in $ports_tcp; do ufw "$([[ $1 == add ]] && echo allow || echo delete allow)" "$p/tcp" >/dev/null || true; done
        for p in $ports_udp; do ufw "$([[ $1 == add ]] && echo allow || echo delete allow)" "$p/udp" >/dev/null || true; done
        echo "firewall: ufw $1"
    elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
        for p in $ports_tcp; do firewall-cmd --permanent --"$1"-port="$p/tcp" >/dev/null || true; done
        for p in $ports_udp; do firewall-cmd --permanent --"$1"-port="$p/udp" >/dev/null || true; done
        firewall-cmd --reload >/dev/null
        echo "firewall: firewalld $1"
    elif command -v iptables >/dev/null; then
        # Oracle Cloud's Ubuntu/Oracle Linux images REJECT everything but SSH in iptables itself.
        local op; [[ $1 == add ]] && op=-I || op=-D
        for p in $ports_tcp; do iptables $op INPUT -p tcp --dport "$p" -j ACCEPT -m comment --comment gb3-server 2>/dev/null || true; done
        for p in $ports_udp; do iptables $op INPUT -p udp --dport "$p" -j ACCEPT -m comment --comment gb3-server 2>/dev/null || true; done
        if command -v netfilter-persistent >/dev/null; then netfilter-persistent save >/dev/null 2>&1 || true
        elif [[ -d /etc/iptables ]]; then iptables-save > /etc/iptables/rules.v4 || true; fi
        echo "firewall: iptables $1"
    else
        echo "firewall: none found (nothing to open)"
    fi
}

if ((uninstall)); then
    systemctl disable --now gb3-server 2>/dev/null || true
    rm -f /etc/systemd/system/gb3-server.service
    systemctl daemon-reload
    firewall remove
    rm -rf /opt/gb3-server
    echo "removed the service and /opt/gb3-server; accounts are kept in /var/lib/gb3-server (delete it by hand)"
    exit 0
fi

[[ $(uname -m) == x86_64 ]] || { echo "this server is built for x86-64 (on Oracle Cloud pick an AMD shape, not Ampere/ARM)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is needed (apt install python3 / dnf install python3)" >&2; exit 1; }
src=$top/runtime/shadnet
[[ -x $src/shadnet ]] || { echo "server files not found in $src (run this from the unpacked release)" >&2; exit 1; }

systemctl stop gb3-server 2>/dev/null || true
rm -rf /opt/gb3-server.new
mkdir -p /opt/gb3-server.new
cp -a "$src" /opt/gb3-server.new/shadnet
cp -p "$here/gb3net.py" /opt/gb3-server.new/gb3net.py
cp -p "$here/README.md" "$here/shadnet-gb3.diff" /opt/gb3-server.new/ 2>/dev/null || true
rm -rf /opt/gb3-server && mv /opt/gb3-server.new /opt/gb3-server
id gb3server >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gb3-server --shell /usr/sbin/nologin gb3server
mkdir -p /var/lib/gb3-server
chown gb3server: /var/lib/gb3-server
chmod 700 /var/lib/gb3-server

keyfile=/var/lib/gb3-server/registration-key
if [[ -n $key ]]; then
    printf '%s' "$key" > "$keyfile"; chown gb3server: "$keyfile"; chmod 600 "$keyfile"
fi
cat > /etc/systemd/system/gb3-server.service <<EOF
[Unit]
Description=GUNDAM BREAKER 3 co-op server (shadNet, from the GB3 Recompiler)
After=network-online.target
Wants=network-online.target

[Service]
User=gb3server
WorkingDirectory=/var/lib/gb3-server
ExecStart=/usr/bin/env python3 /opt/gb3-server/gb3net.py serve --shadnet /opt/gb3-server/shadnet --data /var/lib/gb3-server --port $port --no-beacon --key-file $keyfile
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/gb3-server
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now gb3-server
firewall add
sleep 3
if systemctl is-active --quiet gb3-server; then
    ip=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
    echo
    echo "GB3 co-op server is running."
    echo "In the Recompiler: Network > Online server > address  $ip:$port"
    [[ -n $key ]] && echo "                    and server key  (the --key you gave)"
    echo "Cloud firewall: allow TCP $port, $((port + 2)) and UDP $((port + 1)), 3478 (see server/README.md)."
    echo "Logs: journalctl -u gb3-server   and   /var/lib/gb3-server/shadnet.log"
else
    echo "the service did not start: journalctl -u gb3-server -n 50" >&2
    exit 1
fi
