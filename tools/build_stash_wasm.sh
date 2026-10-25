#!/bin/sh
# Build the Stash versions in third_party/stash-* to WebAssembly: site/engines/stash/stash-<version>.wasm.
#
# Same toolchain as build_fruit_wasm.sh (wasi-sdk via WASI_SDK, or Homebrew llvm + wasi-libc + lld).
# Stash searches on a pthread; tools/wasi_pthread_shim.c runs that thread inline instead, which needs
# WebAssembly setjmp/longjmp (legacy EH).
set -e
cd "$(dirname "$0")/.."
if [ -n "$WASI_SDK" ]; then
  CC="$WASI_SDK/bin/clang"
  SYSROOT="$WASI_SDK/share/wasi-sysroot"
else
  BREW=${HOMEBREW_PREFIX:-/opt/homebrew}
  CC="$BREW/opt/llvm/bin/clang"
  SYSROOT="$BREW/opt/wasi-libc/share/wasi-sysroot"
fi
[ -x "$CC" ] || { echo "clang with the wasm32 target not found (set WASI_SDK)" >&2; exit 1; }
mkdir -p site/engines/stash
for dir in third_party/stash-*/; do
  version=${dir#third_party/stash-}
  version=${version%/}
  "$CC" --target=wasm32-wasip1 --sysroot="$SYSROOT" \
    -O3 -DNDEBUG -w -D_WASI_EMULATED_PROCESS_CLOCKS \
    -mexception-handling -mllvm -wasm-enable-sjlj -mllvm -wasm-use-legacy-eh=true \
    -include tools/wasi_pthread_shim.h -I "$dir/src/include" \
    "$dir"/src/sources/*/*.c tools/wasi_pthread_shim.c -o "site/engines/stash/stash-$version.wasm" \
    -L"$SYSROOT/lib/wasm32-wasip1" -lm -lwasi-emulated-process-clocks -lsetjmp \
    -Wl,-z,stack-size=8388608
  ls -l "site/engines/stash/stash-$version.wasm"
done
