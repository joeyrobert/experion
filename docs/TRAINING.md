# Training the network

The release net (`nets/experion.bin`, embedded into the binary at compile time) is an
ENN5 net trained on CCRL 40/15 game data. The whole pipeline lives in `tools/`.

## Architecture (ENN5)

- Inputs: 768 piece-square features per perspective, times 8 king buckets. Each
  perspective is relative to its own king (black is flipped vertically) and mirrored
  horizontally when its king stands on files e-h. Bucket layout is `KBMAP` in
  `tools/train_v5.py`; `Nnue.king_ctx` in `src/experion/nnue.cr` must match it exactly.
- Feature transformer: 768*8 -> H (H=256 for the release), int16, shared by both
  perspectives, bias folded into the accumulator.
- Activation: SCReLU (`clamp(x, 0, 255)^2`) on `[side to move, other side]`.
- Output: one weight vector per output bucket (`(pieces - 2) / 4`, 8 buckets), plus a
  learned material lane (P N B R Q in centipawns) added directly to the result.
- Quantization: feature transformer scale 255, output weights scale 64. Everything is
  exported by `Net.export` and loaded by `Nnue.load_v5`.

## Pipeline

```sh
# 1. Extract quiet, annotated positions from the CCRL commented PGN (parallel, ~40 min)
python3 tools/extract_ccrl_v5.py CCRL-4040-commented.pgn datasets/v5_chunks --chunk-mb 32

# 2. Dedup globally, pack boards to 32 bytes/position, split train/val by game hash
python3 tools/merge_v5.py datasets/v5_chunks datasets/v5_full

# 3. Train (data lives on the GPU; DDP across GPUs with torchrun, or one GPU with python)
torchrun --nproc_per_node=2 tools/train_v5.py datasets/v5_full run --h 256 --epochs 6 --lam 0.1

# 4. Cross-check the engine's integer inference against the torch model
python3 tools/check_v5.py run/epoch-006.pt 256

# 5. Ship it
cp run/epoch-006.bin nets/experion.bin && shards build --release
```

## Lessons that cost time

- **CCRL score sign conventions are mixed.** Early games are White-POV, most later games
  are mover-POV. Nets trained assuming White-POV everywhere learn almost nothing about
  material. `extract_ccrl_v5.py` decides per game (White-POV series are smooth ply to
  ply, mover-POV series alternate) and skips ambiguous games. After any new extraction,
  check that the correlation of the label with material and with the game result is
  clearly positive, and that a start position minus a rook evaluates near -500.
- **Weight the label, not the result.** The training target is
  `(1 - lam) * sigmoid(cp / 400) + lam * result`. lam=0.5 lost 190 Elo against lam=0.25,
  and lam=0.1 beat lam=0.25 by about 90 Elo.
- **Width barely matters, speed does.** H=256 beat H=512 by about 90 Elo at equal time
  and tied H=128. Validation loss saturates around 0.0116 (lam 0.25) well before
  overfitting shows up as a train/val gap.
- **Validation loss does not rank nets across targets.** Compare nets by playing them
  (`tools/match/ab.sh`), not by loss.

## Self-play data (gendata-v5)

The CCRL labels above are noisy and limited to what CCRL games contain. The
self-play generator (`bin/experion gendata-v5`) produces the next generation of
labels from Experion's own search: fixed node budget per move, the search score
from the side-to-move's POV, plus the eventual game result. See the header of
`src/experion/gendata_v5.cr` for the 64-byte record format and all tuning
envs; the rules (random opening plies with a ±400 discard filter, skip
positions in check / capture-promo best moves / mate scores, adjudication at
|score| > 2500 for 4 plies and |score| < 10 for 10 plies after move 40) come
from `docs/plans/2026_10_27_BEAT_GLAURUNG_WYLD_STASH.md` phase 3.

```sh
# 1. Generate (append + rotate per worker; rerun with the same dir to resume,
#    the position target is cumulative). Measured on the 4-core Linux test
#    box: ~370 positions/s with 4 workers at the default 5k/10k node budget.
#    The plan measured ~3k pos/s on the 10-core Mac at 10 workers, so the
#    150M target is a ~14h overnight run there.
# Mac, plan target (10 workers, ~14h):
bin/experion gendata-v5 150000000 datasets/selfplay_v5 10
# Test box run that produced the current handoff batch (~12h, 15M):
bin/experion gendata-v5 15000000 datasets/selfplay_v5 4

# 2. QA before packing: byte-exact format contract against the engine,
#    record/board validity, and the label sanity checks (score/material and
#    score/result correlations must be clearly positive).
python3 tools/v5_qa.py datasets/selfplay_v5 --engine bin/experion

# 3. Pack into the same npy triplets merge_v5.py writes (dedup by hash,
#    train/val split by GAME).
python3 tools/pack_v5.py datasets/selfplay_v5 datasets/v5_selfplay

# 4. Train and gate, same as below:
torchrun --nproc_per_node=2 tools/train_v5.py datasets/v5_selfplay run_sp --h 256 --epochs 6 --lam 0.1
python3 tools/check_v5.py run_sp/epoch-006.pt 256
# net-vs-net SPRT (candidate via EXPERION_NNUE vs the shipped net), then
# gauntlet.sh / ab.sh before shipping anything.
```

Notes:

- lambda: self-play scores are more self-consistent than CCRL cross-engine
  scores, so the plan's optimum at lam 0.1 must be re-tested at 0.1, 0.2 and
  0.3 with this data. Try self-play data alone first, then a 50/50 mix with
  the CCRL set.
- Do not judge a net by validation loss; play it (see Testing changes).
- A self-play net that loses to the CCRL net at equal data volume is almost
  always a label sign/POV bug; the v5_qa.py correlations are the guard, and a
  start position minus a rook must still evaluate near -500.

## Testing changes

- `tools/match/ab.sh "<env A>" "<env B>" 100` plays two configurations of the same binary
  against each other (single thread, several games in parallel).
- `EXPERION_DISABLE` (comma separated: `nmp lmr fut lmp razor rfp seep sing recap iir chk`)
  turns individual search features off; the defaults disable `chk,recap,sing,lmp`, which
  each measured as a loss.
- `EXPERION_NNUE=/path/net.bin` overrides the embedded net; an empty value selects the
  classical evaluator. `EXPERION_NNUE_VERIFY=1` checks every incremental accumulator
  against a full refresh.
