# Stash as used by Experion's web player

The `stash-<version>` directories hold the `src` tree and `LICENSE` of four releases of **Stash** by
Morgan Houppin, GNU General Public License, version 3 or (at your option) any later version. They
were exported with `git archive` from https://github.com/mhouppin/stash-bot at these tags:

| directory | tag | commit | CCRL Blitz |
| --- | --- | --- | --- |
| `stash-14.0` | `v14` | `d87eaa36ffdf778ba1fee05ce34861f89ac610e9` | 2058 |
| `stash-17.0` | `v17.0` | `f85863d68b2f20812f8e1b330cd2613212a1b12a` | 2297 |
| `stash-21.0` | `v21.0` | `6dc8c9cdefaa43e3d82a7c59cd2a5f93bcbd9d5a` | 2713 |
| `stash-25.0` | `v25.0` | `664849453d3fa0b5b60869325a3764921c902512` | 2933 |

(`v14` keeps its sources at the repository root; they were moved under `src/` here.)

They are compiled to WebAssembly by `tools/build_stash_wasm.sh` and served as
`site/engines/stash/stash-<version>.wasm`. Corresponding source for those binaries is these
directories plus `tools/wasi_pthread_shim.h` and `tools/wasi_pthread_shim.c`.

## Modifications

- Not a source change: every file is compiled with `tools/wasi_pthread_shim.h` force-included. It maps
  the pthread calls onto a single-threaded shim that runs the engine thread inline when the UCI loop
  signals it, because WebAssembly in the page has no threads.
- `stash-14.0`, `stash-17.0`, `stash-21.0`: in `engine/engine_go.c` and `engine/search_bestmove.c`,
  the elapsed-time argument of the `info ... time %lu` lines is cast to `unsigned long`. `clock_t` is
  64 bits on wasm32 while `long` is 32, so without the cast the score that follows prints as `(null)`.
