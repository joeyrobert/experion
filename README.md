# Experion

A UCI chess engine written in Crystal by Joey Robert, with a neural network
evaluation (NNUE) trained from scratch on CCRL game data.

```
     ___         _             
 ___|  _|___ ___| |_ _ _ ___ ___ 
|  _|  _| -_| .'|  | | | .'|  _|
|_| |_| |___|__,|_|\___|__,|_|  
```

## Download

Prebuilt executables for Linux (static), macOS (Apple silicon and Intel) and
Windows are attached to each [release](../../releases). The network is embedded in
the executable, so there is nothing else to install. Point any UCI GUI at it.

## Strength

RESULTS_TABLE

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
