#!/usr/bin/env bash
# Build dist/Recompiler_Gundam_Breaker_3_Break_Edition-x86_64.AppImage
#
#   bash packaging/build-appimage.sh
#
# Needs: podman (rootless) with the fedora:45 container "gb3r-build" (created on first use, with
# squashfs-tools, python3, python3-tkinter), and an AppImage type-2 runtime at
# packaging/appimage-runtime-x86_64 (static runtime from github.com/AppImage/type2-runtime, MIT).
# If that file is missing it is taken from the first ~/Applications/*.AppImage whose runtime is the
# 944,632-byte static type-2 one.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
pod() { if command -v podman >/dev/null 2>&1; then podman "$@"; else distrobox-host-exec podman "$@"; fi; }
cd "$here"

rt=packaging/appimage-runtime-x86_64
if [[ ! -s $rt ]]; then
    for a in "$HOME"/Applications/*.AppImage; do
        python3 - "$a" "$rt" <<'P' && break
import struct, sys
src, dst = sys.argv[1:3]
with open(src, 'rb') as f:
    h = f.read(64)
    if h[:4] != b'\x7fELF' or h[8:11] != b'AI\x02':
        sys.exit(1)
    shoff = struct.unpack_from('<Q', h, 0x28)[0]
    ent, num = struct.unpack_from('<HH', h, 0x3a)
    end = shoff + ent * num
    f.seek(0); rt = f.read(end)
    if f.read(4) != b'hsqs' or b'fusermount3' in rt or len(rt) != 944632:
        sys.exit(1)
open(dst, 'wb').write(rt)
print('runtime taken from', src)
P
    done
fi
[[ -s $rt ]] || { echo "no AppImage runtime: put the type2 runtime-x86_64 at $rt" >&2; exit 1; }

bash packaging/stage.sh "$here/build/AppDir"
if ! pod container exists gb3r-build; then
    pod run -d --name gb3r-build -v "$here":/w:Z -w /w registry.fedoraproject.org/fedora:45 sleep infinity
fi
pod start gb3r-build >/dev/null
pod exec gb3r-build bash -c 'rpm -q squashfs-tools python3-tkinter >/dev/null 2>&1 ||
    dnf install -y -q --setopt=install_weak_deps=False squashfs-tools python3 python3-tkinter binutils'
pod exec gb3r-build bash /w/packaging/bundle-python.sh /w/build/AppDir
cp packaging/AppRun packaging/gb3-recompiler.desktop packaging/gb3-recompiler.svg build/AppDir/
cp packaging/gb3-recompiler.svg build/AppDir/.DirIcon
chmod +x build/AppDir/AppRun
mkdir -p dist
out=dist/Recompiler_Gundam_Breaker_3_Break_Edition-x86_64.AppImage
pod exec gb3r-build bash -c 'rm -f /w/build/app.squashfs && mksquashfs /w/build/AppDir /w/build/app.squashfs \
    -comp zstd -Xcompression-level 19 -root-owned -noappend -quiet -no-progress'
cat "$rt" build/app.squashfs > "$out.tmp"
chmod +x "$out.tmp"
mv "$out.tmp" "$out"
rm -f build/app.squashfs
ls -la "$out"
sha256sum "$out" | tee "$out.sha256"
