#!/usr/bin/env bash
# Assemble the AppDir payload (no game data, no saves) from this project's working copies.
#
#   bash packaging/stage.sh [APPDIR]       default: build/AppDir
#
# Sources (all in GB3-Port-Scope, see AGENTS.md):
#   psport-bundle/                psport v0.2.0 + this port's host patches (save fix, pad, PSN skip,
#                                 low heap, F1 menu) - lib/, out/psport, licences
#   psport-src/out-bundlecompat-boxfix/gpu/libpsport-gpu.so   GPU library with the shop box fix
#   psport/                       play-gb3.sh, common.sh, fix-interp.py, artifact-debug.sh
#   ../GB3-Launcher/bin/ps4-pkg-tool                           PKG unpacker (GPL-2.0-or-later)
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
scope=$(cd -- "$here/../GB3-Port-Scope" && pwd -P)
launcher=$(cd -- "$here/../GB3-Launcher" && pwd -P)
appdir=${1:-$here/build/AppDir}

GPU_LIB=$scope/psport-src/out-bundlecompat-boxfix/gpu/libpsport-gpu.so
GPU_MD5=e4cf03f2c823276bc2cf0735f895dfa5
[[ $(md5sum < "$GPU_LIB" | cut -d' ' -f1) == "$GPU_MD5" ]] || { echo "boxfix GPU library md5 mismatch" >&2; exit 1; }
[[ $(strings -a "$scope/psport-bundle/out/psport" | grep -c "GB3 startup PSN sign-in question suppressed") -ge 1 ]] \
    || { echo "out/psport is not the patched build" >&2; exit 1; }

rm -rf "$appdir"
mkdir -p "$appdir"/{runtime/psport-bundle/out/gpu,runtime/psport,bin,data,app}
b=$appdir/runtime/psport-bundle
src=$scope/psport-bundle
cp -dR --preserve=mode,timestamps,links "$src/lib" "$src/LICENSE" "$src/LICENSES" "$src/LICENSES.json" "$src/LICENSES.md" \
      "$src/THIRD-PARTY-NOTICES" "$src/SOURCES.txt" "$src/run.sh" "$src/relocate.sh" "$b/"
rm -f "$b/lib/interp"
cp -dR --preserve=mode,timestamps,links "$src/out/psport" "$src/out/psport-gpu-capabilities" "$b/out/"
cp -dR --preserve=mode,timestamps,links "$GPU_LIB" "$b/out/gpu/libpsport-gpu.so"
mkdir -p "$b/patches" "$b/user"
cp -dR --preserve=mode,timestamps,links "$src/patches/README" "$b/patches/" 2>/dev/null || true
# The GPU library above is built from GB3-Port-Scope/psport-src (tag v0.2.0 + local patches).
printf 'psport v0.2.0-gb3 host %s gpu %s\n' "$(md5sum < "$b/out/psport" | cut -c1-12)" "${GPU_MD5:0:12}" > "$b/RUNTIME-VERSION"

for f in play-gb3.sh common.sh fix-interp.py artifact-debug.sh gb3-capture.sh deck-gpu.sh; do
    cp -dR --preserve=mode,timestamps,links "$scope/psport/$f" "$appdir/runtime/psport/"
done

cp -dR --preserve=mode,timestamps,links "$launcher/bin/ps4-pkg-tool" "$launcher/bin/LICENSE-ps4-pkg-tool.txt" "$appdir/bin/"
cp -dR --preserve=mode,timestamps,links "$here/data/patchdata.json" "$here/data/patchdata.bin" "$here/data/patches" "$appdir/data/"
cp -dR --preserve=mode,timestamps,links "$here/app/gb3r" "$here/app/main.py" "$appdir/app/"
find "$appdir/app" -name __pycache__ -prune -exec rm -rf {} +
cp -dR --preserve=mode,timestamps,links "$here/README.md" "$here/LICENSE-NOTES.md" "$appdir/"

# Guard: nothing from the game or a save may be in the payload.
if find "$appdir" \( -name 'eboot.bin' -o -name '*.dat' -o -name '*.pkg' -o -path '*savedata*' -o -name '*.spv' -o -name '*.tex' \) | grep -q .; then
    echo "stage: game/save files found in the payload, refusing" >&2
    find "$appdir" \( -name 'eboot.bin' -o -name '*.dat' -o -name '*.pkg' -o -path '*savedata*' -o -name '*.spv' -o -name '*.tex' \) >&2
    exit 1
fi
du -sh "$appdir"
