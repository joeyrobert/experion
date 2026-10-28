# Glaurung 2.2 as used by Experion's web player

This directory holds `src`, `Copying.txt` and `Readme.txt` of **Glaurung 2.2** by Tord Romstad, GNU
General Public License, version 3 or (at your option) any later version. They come from Debian's
`glaurung_2.2.orig.tar.gz` (SHA-256 `a7e148168154d0ccb22a016d5bfc8daffc3534133e6d07639df8035703725106`);
the prebuilt executables in that archive were not copied.

It is compiled to WebAssembly by `tools/build_engines_wasm.sh` and served as
`site/engines/glaurung/glaurung.wasm`. Corresponding source for that binary is this directory plus
`tools/wasi_pthread_shim.h` (force-included so the pthread declarations compile).

## Modifications

- `src/search.cpp`: no helper search threads are launched when compiled for WASI (`__wasi__`), and
  `src/misc.cpp`: `cpu_count()` returns 1 there, so the search stays on one thread.
- `src/misc.cpp`: `Bioskey()` returns 0 under WASI. The web player feeds the engine a complete UCI
  script on standard input, so there is never input to poll for while searching.
- `src/evaluate.cpp`: the king-safety slope loop in `init_safety()` stops at index 98 instead of 99,
  because it reads `SafetyTable[i+1]`, one element past the end of the array. Modern compilers
  miscompile that out-of-bounds read at `-O2` and above (Stockfish later fixed the same loop).
