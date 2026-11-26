#!/usr/bin/env bash
# Pack the co-op server (shadNet 0.1.9 + this port's two fixes) as a self-contained folder that runs
# on any x86-64 Linux: SteamOS, a desktop, a free cloud VM. Its own glibc loader and every library it
# needs (Qt 6, ICU, OpenSSL, the SQLite driver) come along; nothing is installed on the machine.
#
#   bash packaging/bundle-shadnet.sh [OUT]          default: build/shadnet-runtime
#
# Layout of OUT:
#   shadnet               the server binary (GB3-Port-Scope/shadnet-server/build/shadnet)
#   lib/                  ld-linux-x86-64.so.2 + all libraries (Fedora 45)
#   plugins/sqldrivers/   libqsqlite.so
#   share/                worlds.cfg, scoreboards.cfg, clientversions.cfg (copied to a server's data dir)
#   SOURCE.md             where the source and the two patches are (GPL-2.0-or-later)
#
# Needs: rootless podman and the image localhost/shadnet-runtime:fc45 (the one the shadnetsrv
# container runs; Fedora 45 with the server's runtime packages).
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
server=$(cd -- "$here/../GB3-Port-Scope/shadnet-server" && pwd -P)
out=${1:-$here/build/shadnet-runtime}
pod() { if command -v podman >/dev/null 2>&1; then podman "$@"; else distrobox-host-exec podman "$@"; fi; }

bin=$server/build/shadnet
# The server must carry both local fixes (psport STUN header, self-addressed room messages).
grep -q 'foundSelf' "$server/src/cmd_matching.cpp" || { echo "shadnet source lacks the self room message fix" >&2; exit 1; }
grep -aq 'self=' "$bin" || { echo "$bin is not the self room message build" >&2; exit 1; }

rm -rf "$out"
mkdir -p "$out/lib" "$out/plugins/sqldrivers" "$out/share"
cp -p "$bin" "$out/shadnet"
cp -p "$server/worlds.cfg" "$server/scoreboards.cfg" "$server/clientversions.cfg" "$out/share/"

pod run --rm -w / -v "$out":/out:Z -v "$server/build":/sbin-shadnet:ro,Z localhost/shadnet-runtime:fc45 bash -c '
set -e
plug=$(ls -d /usr/lib64/qt6/plugins/sqldrivers)
cp -L "$plug/libqsqlite.so" /out/plugins/sqldrivers/
for f in /sbin-shadnet/shadnet /out/plugins/sqldrivers/libqsqlite.so; do ldd "$f"; done |
    awk "/=> \\//{print \$3} /^\\s*\\/lib64\\/ld-linux/{print \$1}" | sort -u |
    while read -r so; do cp -L "$so" /out/lib/; done
cp -L /lib64/ld-linux-x86-64.so.2 /out/lib/
# glibc pieces loaded at run time (NSS for getaddrinfo/user lookups, gconv is not used by Qt).
for so in libnss_files.so.2 libnss_dns.so.2 libresolv.so.2; do [ -e /lib64/$so ] && cp -L /lib64/$so /out/lib/ || true; done
rpm -qf $(ls /out/lib | sed "s,^,/lib64/," ) 2>/dev/null | sort -u > /out/share/PACKAGES.txt || true
'
cat > "$out/SOURCE.md" <<'EOF'
# GB3 co-op server

shadNet server 0.1.9 (upstream commit a53dad5, GPL-2.0-or-later, https://github.com/shadps4-emu/shadNet)
with two local fixes made for GUNDAM BREAKER 3 co-op:

1. `src/stun_server.cpp/.h`: also accept psport's signaling frames (`FF FF FF FF` + payload) and
   reply with the sender's own header (upstream only accepts `FF 83 FF FF FF FF`).
2. `src/cmd_matching.cpp` CmdSendRoomMessage: a room message addressed to the sender is delivered
   back to it, a broadcast is echoed to the sender, unknown targets no longer fail (RPCN/PSN
   behaviour). GB3's host messages itself before it accepts a joiner.

The patch is `shadnet-gb3.diff` in the Recompiler's `server/` folder. The libraries in `lib/` are
unmodified Fedora 45 packages (list in `share/PACKAGES.txt`); their sources are at
https://src.fedoraproject.org/.
EOF
du -sh "$out"
