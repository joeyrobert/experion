# Experion

A UCI chess engine written in Crystal by Joey Robert.

```
     ___         _             
 ___|  _|___ ___| |_ _ _ ___ ___ 
|  _|  _| -_| .'|  | | | .'|  _|
|_| |_| |___|__,|_|\___|__,|_|  
```

## Features

- **Bitboards** with fancy magic sliders, baked constants via codegen
  (`tools/gen_magics.cr` → `src/experion/magic_constants.cr`)
- **Fully legal move generation** (checkers/pins/check-mask, Stockfish-style)
  — bulk-counted perft runs at hundreds of millions of NPS
- Copy-make position model (value-struct, no undo stacks)
- Incrementally maintained material+PSQT, tapered evaluation with pawn
  structure / mobility / king shelter terms
- Iterative-deepening alpha-beta: PVS, transposition table, null-move pruning,
  LMR, futility pruning, killer/history ordering, quiescence with delta pruning
- UCI protocol (passes fastchess compliance checks)

## Performance (Apple M5)

| metric | value |
| --- | --- |
| legal move generation | ~780M moves/sec |
| bulk perft (startpos d5+) | ~400M nps |
| search | ~10M nps |

## Usage

```sh
shards build --release

bin/experion                 # UCI mode (default)
bin/experion perft 6         # perft from startpos
bin/experion divide 3 FEN    # per-root-move breakdown
bin/experion bench           # movegen + perft throughput
bin/experion epdtest suites/wac.epd 200   # solve WAC at 200ms/move
bin/experion search 12 FEN   # quick non-UCI search
crystal spec                 # 645 perft tests incl. full reference suite
```

## Testing

Move generation is verified against the complete TalkChess/ceruleanjs perft
suite (131 positions, every listed depth) plus the canonical six CPW positions
at depth 4–6, and a bulk-vs-non-bulk cross-check. See `spec/perft_spec.cr`.

## Results (fastchess, 10+0.1, Apple M5, 7 threads)

| opponent | score |
| --- | --- |
| TSCP 1.81 | 192–5–3 (+589 Elo, 200 games) |
| CeruleanJS | 40–0–0 (40 games) |
| Crafty 25.2 (1 cpu) | ≈ −300 Elo across repeated 40-game matches (best single: 7–31–2, −241) |

Direct A/B (30 games): current NNUE net 0–30 vs classical eval — nets remain
a research track, not yet competitive.

Search: PVS + TT + null-move + LMR/IIR + futility + bounded check extensions,
SEE-ordered/pruned quiescence with TT, counter-moves + 1-ply continuation
history, killer/history heuristics, lazy SMP with per-worker diversity.

## NNUE (in progress)

Full pipeline exists: `experion gendata[-classical]` → `tools/nnue_train.py`
(PyTorch) → `nnue.bin` loaded by `src/experion/nnue.cr` with incrementally
updated accumulators (verified exact against full refresh). Toggle with
`setoption name Use NNUE true|false`. Current nets are weaker than the
classical eval — they need millions of training positions and result-based
fine-tuning to pass it. Roadmap to Crafty strength:

1. scale self-play data (millions of positions, deeper searches)
2. train on search scores, then fine-tune on game results
3. king-bucket feature factorization + bigger hidden layer
4. SPRT-gated classical search improvements along the way

## Tuning

`experion gendata` produces self-play training positions; `tools/texel_tune.cr`
fits the PSQT tables to game results and regenerates
`src/experion/psqt_tuned.cr`.

## Match tooling

`tools/match/` contains fastchess, a UCI↔XBoard bridge (`uci_bridge.cr`) for
testing against classic XBoard engines such as TSCP and CeruleanJS, opening
books, and `run_match.sh`.

## License

MIT
