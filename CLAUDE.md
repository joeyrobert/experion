# Experion

UCI chess engine in Crystal. See README.md for overview.

## Commands

```sh
shards build --release          # or: crystal build --release -o bin/experion src/experion_cli.cr
crystal spec                    # perft + ENN5 accumulator specs (must stay green)
bin/experion                    # UCI mode (default when invoked bare)
bin/experion perft 6 [fen]
bin/experion bench              # movegen + perft throughput
bin/experion epdtest suites/wac.epd 200
bin/experion gendata-selfplay <games> <depth> <out> <threads>   # self-play data (not on Windows)
crystal run tools/texel_tune.cr --release -- /tmp/training.txt 60 40000 1.13
```

## Match testing

```sh
CONC=1 THREADS=4 HASH=256 zsh tools/match/run_match.sh 10+0.1 20 fruit   # also: crafty | sungorus | wyld ...
zsh tools/match/ab.sh "ENV_A=..." "ENV_B=..." 100        # A/B two configs of bin/experion, 1 thread each
```

- fastchess binary + opponents live in `tools/match/`.
- fastchess speaks UCI only; XBoard engines (TSCP, Crafty, CeruleanJS) go
  through `tools/match/uci_bridge` (see its header for the protocol traps it
  handles: no ucinewgame between games, Crafty ignores `new`, feature/SAN
  negotiation, ms→cs clocks, stale-move discard).
- Gauntlets use Threads=4, Hash=256; `ab.sh` uses one thread per side.
- The release net is embedded; `EXPERION_NNUE=<path>` overrides it, empty value = classical.
- `EXPERION_DISABLE` toggles search features (see docs/TRAINING.md); defaults were chosen by A/B.
- Always judge strength by match results, not WAC/STS deltas (±5 noise).

## Crystal gotchas hit by this codebase

- Int `/` returns Float — use `//` for floor division.
- UInt8/UInt16 shifts wrap silently (`11u8 << 6 == 192`): `.to_i` before shifting.
- No wrapping shift operators; plain `<<`/`>>` are unchecked. Use `&+ &- &*`
  for wrap-prone arithmetic.
- Bare `Thread.new` workers have no execution context: NO Crystal IO/Channels
  inside them — use `Raw.write_stdout` (LibC.write / LibC._write on Windows).
- Default `+ - *` are overflow-checked and block LLVM auto-vectorization; the
  NNUE hot loops use `&+ &- &*` (this was worth 2-6x on inference).
- `{% if %}` macros inside a `case` need complete `when` clauses; put platform
  conditionals around whole methods instead.
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
- `eval.cr` — classical evaluator (fallback): tapered PSQT base + dynamic terms;
  tuned overlay via `psqt_tuned.cr`.
- `nnue.cr` — ENN5 loader/inference (embedded `nets/experion.bin`), incremental
  accumulators (`apply_delta`), king-bucket refresh cache. Feature layout must
  match `tools/train_v5.py`. Older ENN3/ENN4 loaders remain for comparison.
- Training: `docs/TRAINING.md`. CCRL score POV is mixed per game (see memory notes).
