#!/bin/sh
# Build Fruit 2.1 (third_party/fruit-2.1) to WebAssembly: site/engines/fruit/fruit.wasm.
#
# Toolchain: either the wasi-sdk (set WASI_SDK to its directory), or on macOS
#   brew install llvm wasi-libc wasi-runtimes lld
# Fruit aborts timed-out searches with longjmp, so this needs WebAssembly exception handling
# (legacy EH, which every current browser and Node 20+ support).
set -e
cd "$(dirname "$0")/.."
if [ -n "$WASI_SDK" ]; then
  CXX="$WASI_SDK/bin/clang++"
  LIBC_SYSROOT="$WASI_SDK/share/wasi-sysroot"
  CXX_SYSROOT="$LIBC_SYSROOT"
else
  BREW=${HOMEBREW_PREFIX:-/opt/homebrew}
  CXX="$BREW/opt/llvm/bin/clang++"
  LIBC_SYSROOT="$BREW/opt/wasi-libc/share/wasi-sysroot"
  CXX_SYSROOT="$BREW/opt/wasi-runtimes/share/wasi-sysroot"
fi
[ -x "$CXX" ] || { echo "clang++ with the wasm32 target not found (set WASI_SDK)" >&2; exit 1; }
mkdir -p site/engines/fruit
"$CXX" --target=wasm32-wasip1 --sysroot="$LIBC_SYSROOT" \
  -isystem "$CXX_SYSROOT/include/wasm32-wasip1/c++/v1" -isystem "$CXX_SYSROOT/include/c++/v1" \
  -O3 -fno-exceptions -fno-rtti -DNDEBUG -w -D_WASI_EMULATED_PROCESS_CLOCKS \
  -mexception-handling -mllvm -wasm-enable-sjlj -mllvm -wasm-use-legacy-eh=true \
  third_party/fruit-2.1/src/*.cpp -o site/engines/fruit/fruit.wasm \
  -L"$CXX_SYSROOT/lib/wasm32-wasip1" -L"$LIBC_SYSROOT/lib/wasm32-wasip1" \
  -lc++ -lc++abi -lwasi-emulated-process-clocks -lsetjmp -Wl,-z,stack-size=8388608
ls -l site/engines/fruit/fruit.wasm
