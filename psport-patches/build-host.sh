#!/usr/bin/env bash
# Builds psport v0.2.0 from this checkout without rebuilding its GPU library: the library linked
# here is the one shipped in the v0.2.0 bundle, which is the same tag, so only the port own C
# sources are compiled. Mirrors the host half of build.sh (same source lists, flags and link).
#
#   GPU_LIB=<bundle>/out/gpu/libpsport-gpu.so [CC=gcc] bash build-host.sh
set -euo pipefail
cd -- "$(dirname -- "$0")"
CC=${CC:-cc}
mkdir -p out out/atrac9 out/gpu
if [[ ! -f out/gpu/libpsport-gpu.so ]]; then
    cp "${GPU_LIB:?set GPU_LIB to the v0.2.0 bundle out/gpu/libpsport-gpu.so}" out/gpu/
fi
read -r -a includes <<< "$(pkg-config --cflags vulkan sdl3)"
read -r -a libraries <<< "$(pkg-config --libs vulkan sdl3)"
if [[ ! -f out/libatrac9.a ]]; then
    for source in third_party/LibAtrac9/C/src/*.c; do
        "$CC" -std=c99 -O2 -g -w -c "$source" -o "out/atrac9/$(basename "${source%.c}").o"
    done
    ar rcs out/libatrac9.a out/atrac9/*.o
fi
areas=(main loader runtime runtime/imports kernel system audio input net platform)
mapfile -t runtime < <(printf '%s\n' src/*/runtime*.c | LC_ALL=C sort -t/ -k3)
"$CC" -std=c11 -O2 -g -Wall -Wextra -Werror -pthread -no-pie \
    -DPS_VERSION="\"$(cat VERSION)\"" -DPS_COMMIT="\"local\"" \
    "${includes[@]}" -I. "${areas[@]/#/-Isrc/}" \
    src/main/main.c src/main/cli.c src/main/game_info.c src/main/bind.c src/main/signals.c \
    src/loader/loader*.c "${runtime[@]}" \
    src/platform/*.c src/platform/common/*.c src/platform/linux/*.c \
    src/main/vulkan_smoke.c out/libatrac9.a -lm \
    -Lout/gpu -lpsport-gpu -rdynamic -Wl,--disable-new-dtags \
    -Wl,-rpath,'$ORIGIN/gpu:$ORIGIN/../lib:/usr/lib/x86_64-linux-gnu:/usr/lib64:/usr/lib:/lib/x86_64-linux-gnu:/lib64:/lib:/run/opengl-driver/lib' \
    -Wl,--allow-shlib-undefined "${libraries[@]}" -o out/psport
echo "Built $PWD/out/psport"
