#!/bin/sh
# Build the vendored opponents in third_party/ to WebAssembly under site/engines/:
# Stash 21, WyldChess 1.51 and Glaurung 2.2 (Fruit has its own script, build_fruit_wasm.sh).
#
# Same toolchain as build_fruit_wasm.sh: the wasi-sdk (set WASI_SDK), or on macOS
#   brew install llvm wasi-libc wasi-runtimes lld
# Stash and WyldChess search on a pthread; tools/wasi_pthread_shim.c runs that thread inline instead,
# which needs WebAssembly setjmp/longjmp (legacy EH).
set -e
cd "$(dirname "$0")/.."
if [ -n "$WASI_SDK" ]; then
  CC="$WASI_SDK/bin/clang"
  CXX="$WASI_SDK/bin/clang++"
  LIBC_SYSROOT="$WASI_SDK/share/wasi-sysroot"
  CXX_SYSROOT="$LIBC_SYSROOT"
else
  BREW=${HOMEBREW_PREFIX:-/opt/homebrew}
  CC="$BREW/opt/llvm/bin/clang"
  CXX="$BREW/opt/llvm/bin/clang++"
  LIBC_SYSROOT="$BREW/opt/wasi-libc/share/wasi-sysroot"
  CXX_SYSROOT="$BREW/opt/wasi-runtimes/share/wasi-sysroot"
fi
[ -x "$CC" ] || { echo "clang with the wasm32 target not found (set WASI_SDK)" >&2; exit 1; }
COMMON="--target=wasm32-wasip1 --sysroot=$LIBC_SYSROOT -O3 -DNDEBUG -w -D_WASI_EMULATED_PROCESS_CLOCKS -D_WASI_EMULATED_MMAN
  -mexception-handling -mllvm -wasm-enable-sjlj -mllvm -wasm-use-legacy-eh=true -include tools/wasi_pthread_shim.h"
LINK="-L$CXX_SYSROOT/lib/wasm32-wasip1 -L$LIBC_SYSROOT/lib/wasm32-wasip1 -lm -lwasi-emulated-process-clocks -lwasi-emulated-mman -lsetjmp
  -Wl,-z,stack-size=8388608"
mkdir -p site/engines/stash site/engines/wyldchess site/engines/glaurung
"$CC" -c $COMMON tools/wasi_pthread_shim.c -o site/engines/wasi_pthread_shim.o

"$CC" $COMMON -I third_party/stash-21/src/include third_party/stash-21/src/sources/*/*.c \
  site/engines/wasi_pthread_shim.o -o site/engines/stash/stash.wasm $LINK

"$CC" $COMMON -std=c11 third_party/wyldchess-1.51/src/*.c third_party/wyldchess-1.51/src/syzygy/tbprobe.c \
  site/engines/wasi_pthread_shim.o -o site/engines/wyldchess/wyldchess.wasm $LINK

# Glaurung: the sources its Makefile builds (timeoday.cpp is a Windows-only helper).
GLAURUNG=""
for f in benchmark bitbase bitboard book color direction endgame evaluate history main material mersenne misc move movegen movepick pawns piece position san search square tt uci ucioption value; do GLAURUNG="$GLAURUNG third_party/glaurung-2.2/src/$f.cpp"; done
"$CXX" $COMMON -fno-exceptions -fno-rtti \
  -isystem "$CXX_SYSROOT/include/wasm32-wasip1/c++/v1" -isystem "$CXX_SYSROOT/include/c++/v1" \
  $GLAURUNG site/engines/wasi_pthread_shim.o -o site/engines/glaurung/glaurung.wasm \
  $LINK -lc++ -lc++abi

rm site/engines/wasi_pthread_shim.o
ls -l site/engines/stash/stash.wasm site/engines/wyldchess/wyldchess.wasm site/engines/glaurung/glaurung.wasm
