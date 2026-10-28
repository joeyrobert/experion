# WyldChess 1.51 as used by Experion's web player

This directory holds the `src` tree, `README.md` and `LICENSE` of **WyldChess 1.51** by Manik Charan,
GNU General Public License, version 3 or (at your option) any later version, exported with
`git archive` from https://github.com/Mk-Chan/WyldChess at tag `v1.51`
(commit `322b028cb5e8ba4d8596ca71071d4a9428782f31`).

It is compiled to WebAssembly by `tools/build_engines_wasm.sh` and served as
`site/engines/wyldchess/wyldchess.wasm`. Corresponding source for that binary is this directory plus
`tools/wasi_pthread_shim.h` and `tools/wasi_pthread_shim.c`.

## Modifications

None to the source. Every file is compiled with `tools/wasi_pthread_shim.h` force-included, which
runs the search thread inline because WebAssembly in the page has no threads.
