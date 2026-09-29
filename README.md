# Experion

A UCI chess engine written in Crystal by Joey Robert, with a neural network
evaluation (NNUE) trained from scratch on CCRL game data.

```
                     _         
 ___ _ _ ___ ___ ___|_|___ ___ 
| -_|_'_| . | -_|  _| | . |   |
|___|_,_|  _|___|_| |_|___|_|_|
        |_|                    
```

## Play it

A playable version runs in the browser at **https://joeyrobert.github.io/experion/** (the engine is compiled
to WebAssembly; single thread, same network and search). To run the site locally:

```sh
tools/build_wasm.sh                      # needs Crystal, lld and wasi-libc; writes site/play/experion.wasm
python3 -m http.server --directory site  # then open http://localhost:8000/play/
node tools/wasm_smoke.mjs                # checks the wasm build
```

## Download

Prebuilt executables for Linux (static), macOS (Apple silicon and Intel) and
Windows are attached to each [release](../../releases). The network is embedded in
the executable, so there is nothing else to install. Point any UCI GUI at it.

## Strength

Local matches with fastchess at 10+0.1 (Apple silicon, Experion on 4 threads, 256 MB hash),
100 games each, the default release binary with its embedded net, no overrides:

| opponent | result | score | Elo |
| --- | --- | --- | --- |
| Fruit 2.1 | 69–17–14 | 76% | +200 ± 74 |
| Crafty 25.2 (fair clocks) | 58–32–10 | 63% | +92 ± 68 |

Both opponents run single-threaded on their default settings. Crafty is driven through
an XBoard bridge that gives it its own clock. These are local head-to-head results, not
rating-list numbers, and the intervals are 95%. Earlier in development Experion scored
21% against Fruit and 5–18% against Crafty; the jump came from correcting the training
labels, a faster and better-targeted network, and removing search features that
measured as losses (see [docs/TRAINING.md](docs/TRAINING.md)).

## Features

- **Bitboards** with fancy magic sliders, baked constants via codegen
  (`tools/gen_magics.cr` → `src/experion/magic_constants.cr`)
- **Fully legal move generation** with bulk-counted perft at hundreds of millions of
  nodes per second; verified against the full TalkChess perft suite
- Copy-make position model (value struct, no undo stacks)
- **NNUE evaluation (ENN5)**: 768 piece-square inputs × 8 mirrored king buckets → 256
  SCReLU units per perspective, side-to-move relative, 8 output buckets, plus a learned
  material lane. Incrementally updated accumulators, with a per-bucket refresh cache so
  king moves only re-apply a piece diff. See [docs/TRAINING.md](docs/TRAINING.md).
- Iterative-deepening PVS with transposition table, null-move pruning, LMR, reverse
  futility and razoring, IIR, SEE-pruned quiescence, killer/history/counter-move/
  continuation-history ordering, lazy SMP
- The classical hand-written evaluator is kept as a fallback
  (`EXPERION_NNUE=` with an empty value selects it)

## UCI options

| option | default | meaning |
| --- | --- | --- |
| `Hash` | 32 | transposition table size in MB |
| `Threads` | 1 | search threads (lazy SMP, up to 8) |
| `Use NNUE` | true | use the network; false selects the classical evaluator |
| `EvalFile` | `<embedded>` | load a different ENN5 net from a file |
| `EvalBlend` | 100 | 0 = classical, 100 = network only |

## Build from source

```sh
shards build --release       # needs Crystal >= 1.21
bin/experion                 # UCI mode (default when invoked bare)
bin/experion perft 6         # perft from startpos
bin/experion divide 3 FEN    # per-root-move breakdown
bin/experion bench           # movegen + perft throughput
bin/experion epdtest suites/wac.epd 300   # solve WAC at 300ms/move
crystal spec                 # perft suite, evaluator and ENN5 accumulator specs
```

The net is compiled in from `nets/experion.bin`. Set `EXPERION_NNUE=/path/net.bin` to
try another net without rebuilding.

## Testing

Move generation is verified against the complete TalkChess/ceruleanjs perft suite
(131 positions, every listed depth) plus the canonical six CPW positions at depth 4–6.
The ENN5 specs check that incremental accumulator updates (including king moves,
castling, en passant and promotions) match a full refresh exactly, and
`tools/check_v5.py` checks the engine's integer inference against the PyTorch model.

## Match tooling

`tools/match/` holds the fastchess helpers: `run_match.sh` for gauntlets against
UCI/XBoard engines (XBoard engines go through `uci_bridge.cr`), `ab.sh` for A/B tests
of two configurations of the same binary, and `sprt.sh`.

## Training

The whole pipeline (CCRL extraction, dedup and packing, GPU training, export and
verification) is in `tools/`; see [docs/TRAINING.md](docs/TRAINING.md).

## License

MIT
