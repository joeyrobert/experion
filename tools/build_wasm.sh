#!/bin/sh
# Build the browser engine (WebAssembly, WASI) into site/play/experion.wasm.
#
# Needs Crystal >= 1.21, wasm-ld (lld) and a wasm32-wasip1 libc (wasi-libc):
#   brew install lld wasi-libc      (macOS)
#   apt install lld wasi-libc       (Debian/Ubuntu)
# Or set WASI_SDK to a wasi-sdk directory (its bin/ must be on PATH for wasm-ld), or WASI_LIB to the
# directory holding libc.a for wasm32-wasip1.
set -e
cd "$(dirname "$0")/.."
WASI_LIB=${WASI_LIB:-}
[ -z "$WASI_LIB" ] && [ -n "$WASI_SDK" ] && WASI_LIB="$WASI_SDK/share/wasi-sysroot/lib/wasm32-wasip1"
if [ -z "$WASI_LIB" ]; then
  for d in /opt/homebrew/opt/wasi-libc/share/wasi-sysroot/lib/wasm32-wasip1 \
           /usr/local/opt/wasi-libc/share/wasi-sysroot/lib/wasm32-wasip1 \
           /usr/share/wasi-sysroot/lib/wasm32-wasip1 \
           /usr/lib/wasm32-wasi; do
    [ -f "$d/libc.a" ] && WASI_LIB=$d && break
  done
fi
[ -n "$WASI_LIB" ] || { echo "wasi-libc not found; set WASI_LIB" >&2; exit 1; }
mkdir -p site/play
# -Dgc_none: no bdw-gc on wasm (the engine allocates its tables once per run);
# -Dwithout_mt: no threads; 16 MB stack for the recursive search.
crystal build --release --no-debug --target wasm32-wasi \
  -Dgc_none -Dwithout_mt -Dwithout_iconv -Dwithout_openssl \
  --link-flags "-L$WASI_LIB -z stack-size=16777216" \
  -o site/play/experion.wasm src/experion_wasm.cr
ls -l site/play/experion.wasm
