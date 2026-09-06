# Experion

UCI chess engine in Crystal. See README.md for overview.

## Commands

```sh
shards build --release          # or: crystal build --release -o bin/experion src/experion_cli.cr
crystal spec                    # 645 perft tests (must stay green)
bin/experion                    # UCI mode (default when invoked bare)
bin/experion perft 6 [fen]
bin/experion bench              # movegen + perft throughput
bin/experion epdtest suites/wac.epd 200
bin/experion gendata <games> <ms> <out> <threads>   # self-play training data
crystal run tools/texel_tune.cr --release -- /tmp/training.txt 60 40000 1.13
```

## Match testing

```sh
CONC=1 zsh tools/match/run_match.sh 10+0.1 25 crafty    # also: tscp | cerulean
```

- fastchess binary + opponents live in `tools/match/`.
- fastchess speaks UCI only; XBoard engines (TSCP, Crafty, CeruleanJS) go
  through `tools/match/uci_bridge` (see its header for the protocol traps it
  handles: no ucinewgame between games, Crafty ignores `new`, feature/SAN
  negotiation, ms→cs clocks, stale-move discard).
- Match config sets `option.Threads=7 option.Hash=256` for Experion.
- Always judge strength by match results, not WAC/STS deltas (±5 noise).

## Crystal gotchas hit by this codebase

- Int `/` returns Float — use `//` for floor division.
- UInt8/UInt16 shifts wrap silently (`11u8 << 6 == 192`): `.to_i` before shifting.
- No wrapping shift operators; plain `<<`/`>>` are unchecked. Use `&+ &- &*`
  for wrap-prone arithmetic.
- Bare `Thread.new` workers have no execution context: NO Crystal IO/Channels
  inside them — use `Raw.write_stdout` (LibC.write) for search-thread output.
- StaticArray type annotations need literal sizes (constants work, arithmetic
  doesn't).
- A delta-prune-style `next` inside a `while` with a manual counter skips the
  increment: infinite loop. Restructure with a flag instead.

## Engine internals map

- `src/experion/tables.cr` — magic bitboards (baked constants from
  `tools/gen_magics.cr` → `magic_constants.cr`), leaper/between/line tables.
- `position.cr` — copy-make value struct; `child = parent; child.make_move(m)`.
- `movegen.cr` — macro-generated fully legal generator (all moves legal ⇒
  bulk-counted perft).
- `search.cr` — PVS, TT, null-move, LMR+IIR, killers/history/countermoves,
  SEE-ordered quiescence, lazy SMP (`think_smp`).
- `eval.cr` — tapered PSQT base (incremental in Position) + dynamic terms;
  tuned overlay via `psqt_tuned.cr`.
