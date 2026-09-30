#!/usr/bin/env sh
# Build and run the cross-language vector test on the host.
#   CC="cc"                      default compiler (CI)
#   CC="python -m ziglang cc"    works on Windows without MinGW (what scripts/*.ps1 use)
# Downloads the pinned mbedTLS 3.x release once into .cache/ and verifies its SHA-256.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
CACHE=${RK_CACHE:-$ROOT/.cache}
MBED_VER=3.6.2
MBED_SHA256=8b54fb9bcf4d5a7078028e0520acddefb7900b3e66fec7f7175bb5b7d85ccdca
MBED_URL="https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-$MBED_VER/mbedtls-$MBED_VER.tar.bz2"
MBED_DIR="$CACHE/mbedtls-$MBED_VER"

mkdir -p "$CACHE"
if [ ! -d "$MBED_DIR" ]; then
    TARBALL="$CACHE/mbedtls-$MBED_VER.tar.bz2"
    [ -f "$TARBALL" ] || curl -fsSL -o "$TARBALL" "$MBED_URL"
    echo "$MBED_SHA256  $TARBALL" | sha256sum -c - >/dev/null || {
        echo "mbedTLS tarball checksum mismatch" >&2
        rm -f "$TARBALL"
        exit 1
    }
    tar -xjf "$TARBALL" -C "$CACHE"
fi

CC=${CC:-cc}
OUT="$CACHE/build"
mkdir -p "$OUT"

# Only the mbedTLS modules the codec needs (see rk_host_config.h).
MBED_SRC=""
for f in aes cipher cipher_wrap constant_time gcm hkdf md platform platform_util sha256; do
    MBED_SRC="$MBED_SRC $MBED_DIR/library/$f.c"
done
COMMON_SRC=""
for f in rk_codec rk_ring rk_device rk_edge rk_ethylene rk_ble rk_cmd rk_clock; do
    COMMON_SRC="$COMMON_SRC $ROOT/firmware/common/src/$f.c"
done

# Each test program is built with -Werror and run; any failure fails the script.
# shellcheck disable=SC2086
for t in test_vectors test_ring_device test_edge_misc; do
    $CC -std=c11 -O1 -Wall -Wextra -Werror \
        -Wno-unused-parameter -Wno-unused-function \
        -DMBEDTLS_CONFIG_FILE='"rk_host_config.h"' \
        -I"$HERE" -I"$ROOT/firmware/common/include" -I"$MBED_DIR/include" -I"$MBED_DIR/library" \
        $COMMON_SRC "$HERE/$t.c" $MBED_SRC -lm \
        -o "$OUT/$t"
    "$OUT/$t"
done
