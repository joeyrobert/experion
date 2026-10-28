# Match harness

Opponent binaries and runners for head-to-head testing. All scripts here are
single source of truth for match settings; never hand-run fastchess with ad-hoc
flags for anything you intend to measure.

## Layout

- `run_match.sh` - head-to-head against one named opponent (fastchess).
- `gauntlet.sh` - Experion vs the three milestone targets in sequence
  (glaurung, wyld, stash). THREADS=1 and HASH=64 baked in per the plan's
  measuring rule; per-opponent PGNs go to `gauntlet_<opponent>.pgn`.
- `sprt.sh` - self-play SPRT candidate vs `bin/experion_baseline`.
- `ab.sh` - A/B two env configs of the same binary (e.g. two nets via
  `EXPERION_NNUE=`).
- `openings.pgn` / `openings.epd` - opening books used by all runners.
- `ladder/` - native opponent binaries (see below).
- `fastchess-mac-arm64/` - the checked-in macOS fastchess (gitignored; fetch
  from the upstream releases at the version the scripts expect).
- `fastchess-linux/` - Linux fastchess, downloaded or built locally
  (gitignored). The scripts select the binary by platform automatically; all
  four scripts use script-relative paths, so they work from any clone.
- `uci_bridge.cr` - XBoard-to-UCI shim for non-UCI opponents (TSCP, Crafty,
  CeruleanJS). Build: `crystal build --release -o tools/match/uci_bridge
  tools/match/uci_bridge.cr`.

## Building the native opponents (Linux)

Built from the vendored sources on a Linux box on 2026-10-28; results go to
`ladder/` (gitignored). These mirror `tools/build_engines_wasm.sh`'s file
lists minus the wasm shim:

- glaurung22: `make` in `third_party/glaurung-2.2/src` (its own Makefile:
  g++ -O3 -fno-exceptions -fno-rtti), then copy the produced `glaurung`
  binary to `ladder/glaurung22`. Its UCI `Threads` option defaults to 4 and
  `Ponder` defaults to true; gauntlet pins `option.Ponder=false` and a
  timemargin (its historical "connection stalls" under fastchess). Match
  runners set Threads=1 for both sides anyway.
- stash21: `make EXE=stash21` in `third_party/stash-21/src` (-O3, C), copy
  to `ladder/stash21`. ~2 Mnps on a modern core.
- wyldchess151: `cc -O3 -std=c11 third_party/wyldchess-1.51/src/*.c
  third_party/wyldchess-1.51/src/syzygy/tbprobe.c -lm -o
  tools/match/ladder/wyldchess151` (plain C11, no special flags; add
  `-pthread` if your libc needs it for the optional threads code).

On macOS the ladder binaries from previous milestones are already present.

## Measuring rules (from docs/plans/2026_10_27_BEAT_GLAURUNG_WYLD_STASH.md)

One thread per side for everything that gets compared. Judge only by match
results; never by WAC/STS deltas or validation loss. Gauntlets against the
three targets run only at phase boundaries; SPRT gates every change against
the current baseline.
