# Stash 21 as used by Experion's web player

This directory holds the `src` tree and `LICENSE` of **Stash 21.0** by Morgan Houppin, GNU General
Public License, version 3 or (at your option) any later version, exported with `git archive` from
https://github.com/mhouppin/stash-bot at tag `v21.0` (commit `6dc8c9cdefaa43e3d82a7c59cd2a5f93bcbd9d5a`).

It is compiled to WebAssembly by `tools/build_engines_wasm.sh` and served as
`site/engines/stash/stash.wasm`. Corresponding source for that binary is this directory plus
`tools/wasi_pthread_shim.h` and `tools/wasi_pthread_shim.c`.

## Modifications

- Not a source change: every file is compiled with `tools/wasi_pthread_shim.h` force-included. It maps
  the pthread calls onto a single-threaded shim that runs the engine thread inline when the UCI loop
  signals it, because WebAssembly in the page has no threads.
- In `engine/engine_go.c` and `engine/search_bestmove.c`, the elapsed-time argument of the
  `info ... time %lu` lines is cast to `unsigned long`. `clock_t` is 64 bits on wasm32 while `long` is
  32, so without the cast the score that follows prints as `(null)`.
