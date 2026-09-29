# NNUE / engine-strength session findings

Session goal: make Experion beat Crafty 25.2 (CCRL ~3041) consistently.
Started NNUE-first, pivoted to search-first after NNUE repeatedly failed
with real evidence (Part 3/4). This document records EVERYTHING tried —
what was found, fixed, what worked, what didn't, and exact instructions
for resuming. **If you're picking this up cold, read this TL;DR, then
jump to "Current repo state & how to resume work" at the very end.**

## TL;DR

- The engine ladder (Vice 1997 / Sungorus 2269 / BBChess ~2465 / Fruit 2.1 2694 /
  Crafty 3041, all CCRL-referenced) is built and verified working end-to-end.
- **NNUE: tried hard, did not work, root cause is architectural not a bug.**
  Four real pipeline/search bugs were found and fixed early on (quantization
  overflow, missing UCI option, TT/PV mismatch, data-corruption in self-play
  generation) — each looked like "the" reason NNUE failed, but after fixing
  all four the net was *correct* by every static sanity check and still lost
  to classical eval in real games (Part 1-2). Diagnosed the real gap as
  positional judgment (STS: 32.4% classical vs 6.8% pure NNUE) and built
  king-relative feature buckets as the architectural fix — implemented
  correctly (bit-for-bit verified against an independent Python
  reimplementation) but **three separate training attempts (4-bucket,
  2-bucket, 2-bucket with 2.5x lower LR) all produced nets that actively
  LOSE games** — worst case 0/40 vs a CCRL-1997 engine (Part 3). NNUE is
  parked, not abandoned — see "Recommended next steps" for what it actually
  needs (far more data, or different feature design) before trying again.
- **Search-first pivot: real, immediate wins.** After NNUE's third failure,
  switched to classical search/infrastructure work and found a genuine
  concurrency bug (a non-atomic shared counter) causing the engine's
  multi-threaded search to actively play worse than single-threaded —
  fixed it, and multi-threading went from catastrophic (0% win rate) to
  matching/beating single-threaded across the whole ladder (Part 5). Also
  built proper statistical (SPRT) self-play testing infrastructure,
  addressing a real reliability problem hit firsthand when a time-management
  change looked fine on one small sample and was actually a regression.
- Classical eval scores **5.0% vs Crafty (3041 CCRL) in a confirmed 50-game
  direct match** (Part 4), and ~6.2% post-SMP-fix (Part 5) — real current
  strength is roughly 1650-1750 Elo, a large (~1300+ Elo) gap to Crafty that
  no single session was ever going to fully close. Progress this session
  should be measured in concrete validated wins (the SMP fix) and ruled-out
  dead ends (three NNUE architectures), not in "did it beat Crafty yet."
- GPU training (RTX 3060) is ~7x faster than this Mac's CPU for NNUE training
  specifically (see benchmarks below), if/when NNUE work resumes.

## Current status (updated live during this session)

- **NNUE: parked, not usable.** No NNUE checkpoint from this session should
  be loaded (`EXPERION_NNUE=...`) in any real match — all three
  king-relative-bucket nets (4-bucket, 2-bucket, 2-bucket+lowLR) actively
  lose games. The flat, pre-bucket net (`nnue_hid128_early.bin`, if it
  still exists from earlier in the session) is the only checkpoint that
  didn't actively hurt play, though it never beat classical eval either.
  Classical eval alone (no `EXPERION_NNUE` set) is the current best config.
- **Classical/search: two real fixes kept, one attempt reverted.**
  (1) TT `@age` atomicity fix (`src/experion/tt.cr`) — real, validated,
  fixes the lazy-SMP regression. (2) An eval-scaled null-move-pruning
  reduction (`src/experion/search.cr`) — informal small-sample evidence
  was positive (5-3-2 over 10 games, 60%), a corrected wider-band SPRT
  test was launched to properly confirm it (see "Current repo state" below
  for whether it concluded and what the verdict was). (3) An
  instability-based time-management extension was tried and reverted after
  a clear regression (8.3% vs an 18.3% baseline, same sample size) — not
  currently in the code.
- **Infrastructure added this session, all reusable going forward:**
  `bin/experion smpdiag` (CLI diagnostic for measuring real per-thread
  search throughput), `tools/match/sprt.sh` (proper statistical self-play
  A/B testing), `tools/nnue_check.py` (bit-for-bit NNUE correctness
  checker independent of the training-time Python model).
- **Direct Crafty match record**: classical eval, Threads=1 (pre-SMP-fix),
  50 games, **2-47-1 (5.0%)** — the largest, first-confirmed sample.
  Threads=4 post-SMP-fix, 40 games: **2-37-1 (6.2%)**. Current build
  (SMP fix + NMP change), stopped early by user request ("stop training")
  at 19 of 40 games: **5-14-0 (26.3%)** — notably higher than either prior
  number, but a partial, unfinished sample; treat as an encouraging signal
  worth re-confirming with a full run, not a proven result. All three used
  the same `10+0.1` time control and `CONC=1`.

## Operations reference (README-style)

### Building and testing
```sh
shards build --release          # release binary → bin/experion
crystal spec                    # 645 perft tests — must stay green after ANY change
bin/experion bench               # raw movegen/perft throughput (not real search nps)
bin/experion smpdiag <threads> <movetime_ms> [fen]   # real per-thread search nps/depth, solo vs concurrent
```

### The engine ladder
CCRL-calibrated opponents, weakest to strongest, all wired into
`tools/match/run_match.sh` by name (third argument):

| Name (arg) | Engine | CCRL rating (approx) | Notes |
|---|---|---|---|
| `vice` | Vice 1.1 | 1997 | native UCI, `tools/match/ladder/vice11` |
| `sungorus` | Sungorus 1.4 | 2269 | native UCI, `tools/match/ladder/sungorus14` |
| `bbc` | BBC 1.2 | ~2465 | native UCI, `tools/match/ladder/bbc12` |
| `fruit` | Fruit 2.1 | 2694 | native UCI, path outside repo: `/Users/joey/Repos/engines/fruit/src/fruit` |
| `crafty` | Crafty 25.2 | 3041 | **XBoard, not UCI** — goes through `tools/match/uci_bridge` |
| `tscp` | TSCP 1.81 | (weak, for smoke-testing) | XBoard via bridge |
| `cerulean` | CeruleanJS | — | XBoard via bridge, external repo path |

Also: `ruffian`, `gnuchess`, or any other path passed directly as the 3rd
argument (falls through to the `*` case).

**Why the bridge exists**: fastchess (the match runner) only speaks UCI.
Crafty/TSCP/CeruleanJS speak the older XBoard protocol. `uci_bridge`
translates between them and handles several protocol traps specific to
these engines (documented in the bridge's own source header) — no
`ucinewgame` between games for some engines, Crafty ignoring plain `new`,
feature/SAN negotiation quirks, ms→cs clock conversion, discarding stale
moves after a restart. If a Crafty/TSCP match behaves strangely, check
the bridge's traffic log/behavior before assuming it's an Experion bug.

**Running a match:**
```sh
CONC=1 zsh tools/match/run_match.sh <tc> <rounds> <opponent>
# e.g.
CONC=1 zsh tools/match/run_match.sh 10+0.1 30 crafty
```
- `CONC=1` is important for any result you intend to trust or compare —
  concurrent games compete for CPU and corrupt timing-based play quality
  (see "Validation protocol" below). The script's own default is `CONC=2`
  when unset, which is fine for a quick smoke test but not for anything
  you'll draw a conclusion from.
- `THREADS=N` overrides Experion's thread count (default 4, validated as
  the best setting for this 4-performance-core machine — see the SMP fix
  in Part 5). `BLEND=N` sets `EvalBlend` (0=pure classical, 100=pure NNUE)
  when NNUE is loaded.
- `EXPERION_NNUE=/path/to/net.bin` (env var, not a script flag) enables
  NNUE — it's opt-in, never loaded by default. Combine with `BLEND`.
- Output: running score printed live; full PGN appended to
  `tools/match/games.pgn` (this file accumulates across the WHOLE
  session's history — when grepping it for a specific match, filter by
  approximate line range or `[White "..."]`/`[Black "..."]` tags, not just
  opponent name, since the same opponent appears many times across
  different experiments).

**Proper statistical (SPRT) self-play testing** — use this instead of a
fixed-round ladder test for anything where the expected effect size is
small (a few Elo), since fixed samples of 20-50 games are demonstrably too
noisy to trust for that (this project's own hard-learned lesson, see
"Validation protocol"):
```sh
cp bin/experion bin/experion_baseline   # snapshot BEFORE making a change
# ... make your change, rebuild bin/experion ...
zsh tools/match/sprt.sh <tc> <elo0> <elo1>
```
- Use a WIDE band (`elo0=0 elo1=15` or `20`) for fast iteration — a narrow
  band like `0/5` can take hundreds-to-thousands of games to resolve and
  is impractical mid-session (learned this the hard way, see Part 5).
- **Critical gotcha, hit this session**: if you `cp bin/experion
  bin/experion_baseline` AFTER already accepting a change into
  `bin/experion`, both binaries become identical and SPRT will just show a
  50/50 coin flip with no information. Always snapshot the baseline
  *before* the change you're testing, or rebuild a clean comparison point
  from git history if you've already lost it.
- Games log to `tools/match/sprt_games.pgn` (separate file from the ladder
  script's `games.pgn`).

### NNUE tooling (currently parked, but functional and documented)
- `tools/nnue_train.py` — the trainer. `python3 tools/nnue_train.py
  data.txt [epochs] [out.bin] [HID=N] [lr=X] [cuda|mps|cpu]`. Exports
  "ENN3" format (king-bucketed HalfKA, 2-layer hidden). See the file's own
  header comment for the full architecture description and the reasoning
  chain that led to king buckets.
- `tools/nnue_check.py` — bit-for-bit correctness checker. Reads a raw
  `.bin` file and reimplements the engine's exact int pipeline in pure
  Python, independent of the training-time float model. Use this BEFORE
  trusting any new checkpoint: `python3 tools/nnue_check.py net.bin
  "<fen>" ...` and diff against `EXPERION_NNUE=net.bin EXPERION_BLEND=100
  bin/experion` on the same FENs via the `eval` UCI command.
- Training data: `training_final.txt` (14.04M rows, FICS games + self-play
  + Crafty-labeled positions) is the proven, validated dataset — both on
  this Mac (`/tmp/training_final.txt`) and the GPU box (below).

### GPU training machine — full setup, already done, ready to use

There is SSH access to a separate machine with real GPUs, set up this
session end-to-end for NNUE training. This is NOT hypothetical or
"could be configured" — the Docker image is pulled, NVIDIA Container
Toolkit is installed and working, and training data already lives there.
A future agent can run a real training job with the commands below with
no additional setup.

- **Access**: `ssh joey@192.168.2.46`. Two GPUs: RTX 3060 (12GB) and GTX
  1650 (4GB). Runs Ubuntu 26.04.
- **Why Docker, not a native venv**: the box's system Python is 3.14,
  which has no PyTorch wheels available yet. Training runs inside
  `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime` (already pulled) via
  Docker with `--gpus all` (NVIDIA Container Toolkit already installed
  and confirmed working this session — don't redo this setup, it's done).
- **VRAM conflict, check before every run**: the 3060 normally hosts an
  LLM-serving systemd service, `llama-server.service`, using ~10.4GB VRAM
  — leaves almost nothing for training. **As of the end of this session
  it is intentionally left STOPPED** (the user's explicit call, not an
  oversight — don't restart it without asking). Check state with
  `systemctl is-active llama-server.service`; if it's active and you need
  the VRAM, `sudo systemctl stop llama-server.service` first, and ask
  before restarting it when done rather than assuming.
- **Where things live on that box**: training data and scripts are under
  `~/experion_train/` (e.g. `~/experion_train/training_final.txt`, the
  same proven 14.04M-row dataset as on this Mac). Copy an updated trainer
  script there with `scp tools/nnue_train.py joey@192.168.2.46:~/experion_train/nnue_train.py`
  before a new run if you've changed it locally.
- **Exact command to launch a training run** (matches what was actually
  run this session — copy/paste and adjust the filename/epochs/HID):
  ```sh
  ssh joey@192.168.2.46 "cd ~/experion_train && nohup sudo docker run --rm --gpus all \
    -v \$(pwd):/w -w /w pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime \
    python nnue_train.py training_final.txt 30 nnue_out.bin HID=128 cuda \
    > train_out.log 2>&1 & echo launched"
  ```
  This backgrounds the job on the remote box (survives your SSH session
  ending) and logs to `train_out.log` in `~/experion_train/`. Poll with:
  ```sh
  ssh joey@192.168.2.46 "tail -20 ~/experion_train/train_out.log"
  ```
  Watch the per-epoch `sanity[...]` line (see "Validation protocol" below)
  — don't just wait for it to finish and trust the final/best-val-loss
  checkpoint blindly, that's caused real problems this session.
- **Retrieve the trained net**: `scp joey@192.168.2.46:~/experion_train/nnue_out.bin
  /Users/joey/Repos/experion/nnue_out.bin`, then validate with
  `tools/nnue_check.py` (above) BEFORE any match testing.
- **Measured performance** (why bother with this machine at all): CUDA on
  the 3060 is ~7x faster than this Mac's CPU and ~3x faster than this
  Mac's own GPU (MPS) for this specific training workload — full numbers
  and why (sparse gather/scatter pattern, MPS kernel immaturity) in the
  "GPU training" section further down this document.

## Bugs found and fixed

### 1. NNUE quantization overflow (`OUT_SHIFT`)

`tools/nnue_train.py` exported the trained float `w2` output-layer weights as
`round(w2 * 2^OUT_SHIFT)` clipped to `int16`. `OUT_SHIFT` was `20`. Trained `w2`
values commonly reach magnitude 2-3 after real training — `w2 * 2^20` overflows
`int16` (max 32767) by up to ~70x, so most of the output layer was silently
clipped to the same few extreme values on export. This was invisible during
training (the float model looked fine) and only showed up when testing the
*exported, quantized* binary against known positions (e.g. K+2 Rooks vs bare
King evaluating at only +7cp instead of >+1000cp).

Separately, the engine's integer activation path never applied the `/512`
normalization that the Python float model applies before the `w2` matmul —
so even with a safe `OUT_SHIFT`, the engine's output was a constant 512x
python's, compounding with the wrong `>>10` final shift into roughly a 2x
systematic error.

**Fix:** `OUT_SHIFT` lowered to `12` (keeps realistic `w2` magnitudes safely
inside `int16`), and the final `cp = (blended * 600) >> 10` corrected to
`>> 9` to cancel the missing `/512` factor. Verified: exported net now matches
the trained float model to the cp, e.g. K+2R vs K: 373cp engine vs 372cp float.

### 2. UCI `EvalBlend` option never declared

The engine's `"uci"` handshake response never included
`option name EvalBlend type spin ...`. Strict UCI tools (fastchess) refuse to
send `setoption` for options a "uci" response didn't declare — so essentially
every `BLEND=X` match-testing run earlier in the session silently ran at the
compiled-in default (blend=100, pure NNUE) regardless of what was requested.
Confirmed via fastchess's own warning: `Warning; Experion doesn't have option
EvalBlend`. Fixed by declaring the option in `uci.cr`'s `"uci"` handler.

### 3. Root TT/PV mismatch

`search_root` (in `search.cr`) picked the engine's actual best move via its own
`@moves[]` array, but never stored that decision into the transposition table.
The UCI `info ... pv` line is reconstructed by walking the TT from the root
position — so it was reporting whatever move a *transposing child node*
happened to leave in that TT slot, which frequently differed from the actual
`bestmove` sent to the GUI. fastchess flagged this on nearly every move
("Warning; Bestmove does not match beginning of last PV"). Fixed by storing
the root's own decision (move, score, correct EXACT/LOWER/UPPER flag) into the
TT right after search_root's move loop.

Confirmed via an isolated-TT diagnostic that this is unrelated to the SMP
regression below (see that section) — it's a real but separate bug.

### 4. Self-play data generator: TT collision corrupting early-opening labels

`gendata-scored`'s `scored_worker` creates **one** `Searcher` (and its TT) per
worker thread, then reuses it across all ~5,000 distinct random-walk games
that thread generates, without ever calling `new_game` between games. The
table was only 2^18 (262,144) entries. Early-opening positions recur across
*nearly every one* of those thousands of games (there just aren't that many
distinct positions after 1-2 random plies), so this small, never-cleared table
saw heavy, consistent hash collisions specifically for the small set of early
positions — corrupting their search-based score labels in a consistent
direction (not random noise), because the same colliding slot kept getting
reused across many different games' identical/near-identical early positions.

This directly explained the previous net's severe **opening-phase bias**:
+835cp at the starting position and +700-1000cp after completely normal
opening moves (1.e4 e5, 1.d4 d5, 1.Nf3 Nf6), when these should be ~0. That bias
made blending the net in at *any* percentage (even 15%) actively harmful,
because every single game started with a badly miscalibrated evaluation.

**Fix:** table size raised to 2^20 (1M entries) and `s.new_game` called once
per game (clears TT + killers/history). Verified directly: regenerated data's
average score dropped from a systematic +115cp bias to a sane +11.5cp, and
individual early-opening positions in the new data show realistic small values
(11, 49, -51, 148cp) instead of 700-1000+.

### 5. (Also fixed, smaller) self-play generator could hang indefinitely

Uniform-random move walks up to ~100 plies occasionally reach pathological
positions (mass promotions, chaotic material) that blow up search cost with no
time/node safety net — only a depth cap. One such run hung for 100+ minutes
producing zero output. Fixed with a 300k-node hard cap per position (Limits
already supported `nodes_max`; it just wasn't being set here). Cut that
specific hang from 100+ minutes to 6 seconds for an equivalent-sized batch.

## Known issue, not resolved: lazy-SMP hurts play quality

Single-threaded search measurably **outperforms** 8-threaded lazy-SMP in real
games — e.g. 17.5% (3-16-1/20) vs Vice single-threaded, ~0% at Threads=8 in an
otherwise identical match setup. This is the opposite of the expected SMP
benefit.

What was ruled out:
- **Not raw throughput/CPU contention**: a fixed-depth comparison showed the
  primary thread reaches the same nominal depth *faster* with 8 threads
  (955ms vs 2487ms for depth 12), and picked the same best move in that test.
- **Not shared-TT pollution**: re-ran with each worker given its own isolated
  (non-shared) TT instead of `@tt` — still ~0% at 8 threads. So it's not
  workers writing bad entries into a table the primary also reads.

Root cause is still unknown. Given the ladder/match-testing infrastructure
needs a reliable signal, `run_match.sh` now defaults to `THREADS=1` (override
available) since that's empirically the stronger configuration until this is
properly diagnosed.

**A third hypothesis was tested and also ruled out.** This machine has only
4 physical performance cores (+ 6 efficiency cores, `sysctl -n
hw.perflevel0.physicalcpu hw.perflevel1.physicalcpu` → 4, 6), but the
documented Threads=8 failure oversubscribes P-cores 2x — plausible that
naive `Thread.new` scheduling under real (not fixed-depth) time pressure
degrades the primary thread's own throughput via cache/memory contention
or getting scheduled onto slower E-cores. Tested Threads=4 (matching the
P-core count) vs Vice, same time control: **0-7-0 through 7 games** — the
same total-collapse signature as Threads=8, not meaningfully better.
(One methodology note from this test: an orphaned process from an
unrelated killed match was found still consuming CPU partway through and
contaminated the first ~3 games before being caught and killed — a
reminder to always re-check `ps aux` for stray engine/opponent processes
after any `kill` on a match, not just the top-level fastchess PID.)

**Found and fixed in a follow-up session: a real, previously-undetected
data race — `TT#@age` was a plain `UInt8` field, bumped via `bump_age`
(non-atomic read-modify-write) from every thread in `think_smp`, since all
threads share the same `@tt` instance in the real match path.** Two
distinct bugs stemmed from this: (1) the increment itself could lose
updates under concurrent access, and (2) far worse, `store()`'s
replacement-policy check read `@age` a second time via a fresh,
un-synchronized load (`(flags.to_u64 | (@age.to_u64 << 2))`) that could
race against another thread's concurrent `bump_age`/`store`, and — because
it was never masked to the entry format's 6-bit field before encoding —
could silently corrupt the depth/hash bits of the packed 64-bit TT entry
if `@age` ever exceeded 63 (which the *unmasked* raw field could, since
only `bump_age` masked its own copy, not the value read at encode time).

First added instrumentation to actually measure something rather than
guess again: `bin/experion smpdiag <threads> <movetime_ms> [fen]` (new CLI
command) runs a fixed-movetime search solo and with N-1 concurrent
isolated-TT workers, reporting the **primary thread's own** nodes/depth/
nps in both conditions. Real numbers on this machine (4P+6E cores):

| Threads | movetime | primary nps ratio (concurrent/solo) |
|---|---|---|
| 2 | 2000ms | 1.00 |
| 3 | 2000ms | 0.98 |
| 4 | 2000ms | 0.95 |
| 4 | 575ms (real per-move budget) | 0.87 |
| 6 | 2000ms | 0.67 |
| 8 | 2000ms | 0.65 |

This confirmed real hardware contention exists and scales with thread
count past the P-core budget, but it's nowhere near large enough (13-35%
throughput loss) to explain a 0/40 total collapse in real games — that gap
between "small measured slowdown" and "catastrophic real-game failure" is
what pointed at a correctness bug rather than a pure performance one, and
led directly to finding the `@age` race above.

**Fixed by making `@age` an `Atomic(UInt8)`, and by capturing one
consistent `cur_age` snapshot per `store()` call for both the replacement
check and the actual encoded value** (`src/experion/tt.cr`). Re-tested
Threads=4 vs Vice, 30 games: **4-23-3 (18.3%)** — up from four separate
prior tests all at ~0% (0/40, 0/17, 0/19, 0/7 across different net/thread
configurations) and now roughly on par with the Threads=1 baseline
(17.5%). **This is the real fix**, not another ruled-out hypothesis.

(Note: this appears to contradict the earlier-documented "isolated TT:
still ~0% at 8 threads" test, which should have sidestepped this exact
race by giving each worker its own `@tt`. That earlier test predates this
session's PGN-based diagnosis and wasn't re-verified against this specific
fix — it's possible that test was itself run under different, possibly
confounded conditions, e.g. a match run that got the classical-eval bugs
fixed later in this same session, or was affected by the process-orphan
contamination issue also found and fixed this session. Not fully
reconciled; flagged here rather than silently dropped.)

**Full post-fix ladder at Threads=4** (10+0.1, `CONC=1`, classical eval,
same conditions as every baseline in this doc):

| Opponent (CCRL) | Score | % | Sample | Threads=1 baseline |
|---|---|---|---|---|
| Vice11 (1997) | 4-23-3 | 18.3% | 30 games | 17.5% (3-16-1/20) |
| Sungorus14 (2269) | 1-12-0 | 7.7% | 13 games (stopped early for time) | not previously tested |
| BBC12 (~2465) | 1-15-0 | 6.2% | 16 games | not previously tested |
| Fruit21 (2694) | 0-16-0 | 0.0% | 16 games | not previously tested |
| **Crafty252 (3041)** | **2-37-1** | **6.2%** | 40 games | **5.0% (2-47-1/50)** |

**Verdict: Threads=4 is now at least on par with, and slightly ahead of,
Threads=1 everywhere it was directly compared** (Vice: 18.3% vs 17.5%;
Crafty: 6.2% vs 5.0% — both within/near overlapping noise given sample
sizes, so this is "no longer actively harmful and plausibly a small real
gain," not a dramatic breakthrough). The steep falloff against
Sungorus/BBC/Fruit/Crafty (7.7% → 6.2% → 0% → 6.2%) mirrors the CCRL
rating gaps themselves (2269→2465→2694→3041) rather than showing new
threading-specific damage — consistent with the search-depth/efficiency
gap already diagnosed from the Crafty PGN analysis, not a leftover SMP
bug. **The critical result is that Threads=4 no longer collapses to ~0%
against weak opponents the way it catastrophically did before this fix.**
This makes `Threads=4` usable going forward (real per-move node/sec
headroom from parallelism, without the correctness bug destroying it).

Still untested: whether Threads=6-8 are now also safe (the raw throughput
data above suggests 6+ pays a real hardware-contention cost on this
4-performance-core machine, so parity there is less certain even with the
bug fixed) — left for a future session; `Threads=4` is the validated,
recommended default for this hardware going forward.

## NNUE training runs this session (chronological)

| Net | Data | Key fix applied | Result |
|-----|------|------------------|--------|
| v3/v4 | 200k FICS (real games), WDL-only or static-eval-only labels | initial FICS pipeline | Degenerate: WDL-only teaches "who wins" not magnitude (K+2R vs K ≈ +7cp) |
| v8 | 200k FICS, classical-eval-scored (real result + real score) | quantization bug found & fixed | Correct magnitudes on paper, but blend testing was invalidated by the EvalBlend bug (#2 above) — every "blend" test had secretly been blend=100 |
| v9 | 700k (FICS + 60k synthetic material-imbalance positions) | synthetic augmentation for score-magnitude coverage | Sane extreme-position magnitudes; still lost to classical at every blend once EvalBlend was actually fixed |
| v10 | 1.78M (v9 data + 1M self-play, **before** TT-collision fix) | LR warmup added | Endgame magnitudes excellent (K+2R: 1128cp) but severe opening bias (+835cp at startpos) from the TT-collision bug — actively harmful at every blend |
| v11 | 2.76M (v9 data + 2M self-play, **after** TT-collision fix) | data corruption fixed | Opening bias gone (startpos: 4cp, normal openings: 2-10cp), strong correct-signed endgame magnitudes (K+2R: 1750cp) — genuinely correct net by every sanity check. **Still loses to classical eval at every blend level tested (0/15/20/25/100%).** |

The consistent verdict: fixing real bugs steadily removed *reasons the net
should obviously fail*, without yet producing a net that's actually stronger
than classical eval in play. That's the expected shape of a genuine
data-scale/architecture ceiling rather than a lingering bug — see the plan
below for what closing it actually requires.

## Training dynamics: the "plateau then break at LR decay" pattern

Every run this session (v6 through v11, before warmup) showed the same shape:
training loss flat at (or barely below) the "always predict zero" baseline
loss for 20-60+ epochs, then a sudden, sharp drop exactly coincident with the
first `StepLR` decay. This is a strong signal that the initial LR (1e-2) is
too aggressive for this architecture/data combination to make stable early
progress — Adam is bouncing around a bad region until the step down, not that
more epochs at the same LR were "needed."

**Fix applied:** `tools/nnue_train.py` now does a short linear LR warmup
(start at `lr/20`, ramp to `lr` over `max(3, epochs//20)` epochs) before the
existing `StepLR` decay schedule. This should eliminate the wasted plateau,
though it wasn't yet isolated as a controlled A/B (the same session also
fixed the TT-collision data bug at the same time) — worth re-verifying in
isolation on a future run.

## GPU training

The trainer was hardcoded to `device = "cpu"`. Added MPS (Apple Silicon) and
CUDA auto-detection/override (`mps`/`cuda`/`cpu` as a CLI arg).

**Measured, same architecture, same code:**

| Device | Batch size | Samples/sec |
|--------|-----------|-------------|
| CPU (M-series, 6 threads) | 128 | ~28,400 (matches real training run: 61 epochs / 2.63M samples in 91.5 min) |
| CPU (M-series, 6 threads) | 4096 | ~43,400 |
| MPS (M-series GPU) | 128 | ~14,800 (**slower** than CPU — GPU dispatch overhead dominates at this batch size) |
| MPS (M-series GPU) | 4096 | ~64,200 (1.5x over CPU-large-batch) |
| CUDA (RTX 3060) | 4096 | **~203,000** (measured on the real 2.63M-sample training run: 11 epochs in 142s) |

Takeaway: this workload is dominated by sparse gather/scatter (`index_add_`
for the variable-length per-position feature lists), not dense matmul. MPS's
kernels for that pattern are comparatively immature — it only pays off at
large batch sizes, and even then modestly. CUDA is a much bigger win (~7x over
CPU measured, ~3x over MPS at the same batch size), consistent with CUDA
having far more mature scatter/gather kernels. A further, not-yet-applied
optimization: swap the manual `index_add_` for `torch.nn.EmbeddingBag(mode=
'sum')`, the properly-optimized PyTorch op for exactly this "sum a variable-
length set of embedding rows" pattern — expected to widen the CUDA advantage
further since EmbeddingBag has notably better CUDA kernels than generic
`index_add_`. Not yet measured.

**Practical setup notes** (for whoever runs this next): the GPU box
(`192.168.2.46`) runs Ubuntu 26.04 with only Python 3.14 available system-wide,
which has no PyTorch wheels yet — training runs inside
`pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime` via Docker with
`--gpus all` (NVIDIA Container Toolkit installed and configured this
session). The 3060 is normally hosting an LLM-serving systemd service
(`llama-server.service`) using ~10.4GB VRAM — stop it first
(`sudo systemctl stop llama-server.service`) to reclaim VRAM for training,
and restart it after (`sudo systemctl start llama-server.service`).

## Part 2: GPU training, architecture, Crafty labeling, and a real king-safety bug

Continuing the same night, with a GPU (RTX 3060, via Docker + NVIDIA Container
Toolkit over SSH — see setup notes above) and the fixes from Part 1 in place.

### GPU-trained nets (v10, v11, gpu_v1, gpu_v2) — still lost to classical

Four more full training runs, each on progressively more/better data (up to
10.26M positions: FICS + synthetic + 7.5M fresh self-play with the
TT-collision fix applied), all on GPU. Sanity checks looked good (correct
signs, strong magnitudes, opening bias gone). **All four still lost to
classical eval at every blend level tested (0/16 at blend=100 was typical).**
This made the pattern impossible to ignore: fixing bugs and scaling data kept
producing *correct* nets, never *stronger-than-classical* nets.

### The real diagnosis: label circularity

`gendata-scored`'s self-play labels come from a depth-6 search whose leaf
nodes use **our own classical eval** — the same eval the net is supposed to
beat. A network trained to imitate "classical eval + shallow search" cannot
exceed classical eval's own ceiling, no matter how much of that data you
generate. Scaling from 200k to 10.26M positions never had a chance of fixing
this, because more data just means more copies of the same ceiling.

Compounding this: in the final combined datasets, real human-game data
(FICS, which encodes genuine strategic knowledge no classical-eval-limited
search can replicate) was diluted to under 5% of the total by volume,
against self-play noise from uniform-random move walks.

**Response:** pulled far more real FICS data (the archives had 20M+ games
available — only 700k had been used) and built `tools/score_with_crafty.py`
to label positions with Crafty's own eval (3041 CCRL, classical-only, no
circularity) instead of our own eval. Crafty labeling throughput is real but
slow — ~0.5-1s/position even with `st 1`, since it needs a genuine deep
search per position, not a lookup. Parallelized across 8 processes, scored
~40k positions in the time available. That's a real, stronger-than-classical
signal, but small relative to the multi-million-position self-play/FICS
data — a future run should either budget much more wall-clock time for
Crafty labeling specifically, or find a faster strong-signal source.

### A second architectural bug found the same way: `loss_of` decided WDL-vs-score globally, not per-row

Separately from the label-circularity issue: `nnue_train.py`'s original loss
selection (`has_scores`/`has_real_results`) was computed **once for the whole
dataset**, not per sample. Mixing FICS (real result, `score=0` placeholder)
with self-play (`result=0.5` placeholder, real score) meant *every* row got
the combined `(l_wdl + l_score)` loss — so FICS rows, which have no real
score, were still trained toward a fake `score=0` target, quietly pulling
every human-game position's evaluation toward zero and diluting its otherwise
clean WDL signal. This had been silently active in every combined-source
training run all session. Fixed with a per-sample mask (see `loss_of` in
`nnue_train.py`) so each row only contributes the loss terms it actually has
real labels for.

### Architecture: validated a 2-layer net helps, on identical data

Built `tools/nnue_arch_experiment.py` — a throwaway pure-Python script (not
the shipped pipeline) training a 1-layer net and a 2-layer net (accumulator →
32-wide clipped-ReLU hidden layer → phase heads) on identical data/epochs/
optimizer. **Result: 2-layer net achieved 1.3746 best val loss vs 1.4045 for
1-layer — ~2.1% relative improvement, real and repeatable, not noise.**

Integrated this into the real pipeline (`nnue_train.py`'s `Net` class, file
format bumped to `"ENN2"`) and the engine side
(`src/experion/nnue.cr`). Quantization for the new layer was derived from
actual trained weight magnitudes at export time (`pick_shift()`), not chosen
in the abstract — exactly the lesson from the `OUT_SHIFT` disaster in Part 1.
**Validated correct**: compared the exported Crystal binary's output against
the Python float model on the standard sanity-check positions before any
match testing — all five matched within a few cp of quantization rounding.
This validation methodology (float-model-vs-engine comparison before ANY
match testing) is now the required check before trusting any new net format.

### Final run of the night: combined everything, and it was worse

Final training run: 2-layer architecture + per-row loss fix + 14.04M
positions (3M FICS-2011 + 1.5M FICS-2025 + 7.5M self-play + 60k synthetic +
40k Crafty-labeled). Training looked the healthiest of the whole session —
smooth continuous loss descent with no stuck plateau, clean decay-boundary
breakthroughs, final val loss 0.7615.

**Sanity check on export was badly degenerate**: K+2 Rooks vs bare King
evaluated at ~1cp (should be four digits), K+3 Rooks vs King at -35cp
(wrong sign entirely). Verified this was **not** a quantization bug — the
Python float model itself produces the same degenerate values, so the
export/engine pipeline is faithfully reproducing a genuinely bad trained
net. This is a real regression versus several earlier, simpler nets in Part 1
that at least got signs and rough magnitudes right.

### Isolating the regression: cleanly ruled out architecture, loss fix, and data composition — it's dataset SIZE itself

Followed the document's own advice (below) and isolated each changed
variable instead of guessing. Built `tools/nnue_arch_experiment.py` into a
proper 2x2 matrix (architecture x loss-mode) plus a targeted follow-up, all
run on GPU for fast turnaround:

| Test | Data | Architecture | Loss mode | Epochs | Result |
|------|------|---------------|-----------|--------|--------|
| 1 | 2.85M (old mix: FICS-v9 + self-play-v2) | 1-layer | combined (old) | 60 | **Correct**: K+2R 640cp, K+3R 649cp, Q -638cp |
| 2 | same 2.85M | 1-layer | per-row (new) | 60 | **Correct**: K+2R 547cp, K+3R 562cp, Q -530cp |
| 3 | same 2.85M | 2-layer | combined (old) | 60 | Mostly correct, one sign error: K+2R 1631cp, K+3R 1136cp, Q **+224cp** (wrong sign) |
| 4 | same 2.85M | 2-layer | per-row (new) | 60 | **Correct, best of all four**: K+2R 976cp, K+3R 909cp, Q -748cp; also lowest val loss (0.6993) |
| 5 | 3M *random sample of the exact final 14.04M dataset* | 2-layer | per-row | 60 | **Correct, best of the whole session**: K+2R 1551cp, K+3R 1402cp, Q -1195cp |
| 6 | the **full** 14.04M dataset (same data as #5, just all of it) | 2-layer | per-row | 60 (matched to #5, not the original 120) | **Degenerate again**: K+2R 32cp, K+3R -57cp (wrong sign), Q -36cp; near-constant output across different openings (30/30/30/-30cp) |

Tests 1-4 show neither the 2-layer architecture nor the per-row loss fix is
inherently broken — in fact combo 4 (2-layer + per-row, the exact
configuration used in the failed final run) was the *best* of the four. Test
5 shows the new data sources (2011/2025 FICS, fresh self-play, Crafty labels)
aren't the problem either — a random 3M-row sample of the *identical*
population that make up the full 14.04M dataset trains perfectly. Test 6
shows it isn't epoch count either — collapsed just as badly at 60 epochs
(matching test 5) as it did at the original 120.

**Follow-up: binary-searched the actual cliff location**, same config
(2-layer/per_row, 60 epochs) on progressively larger random-prefix samples
of the identical shuffled `training_final.txt` population:

| Rows | Result |
|------|--------|
| 3M | Correct: K+2R 1551cp, K+3R 1402cp, Q -1195cp |
| 7M | Correct: K+2R 1126cp, K+3R 343cp, Q -526cp |
| 8.75M | **Borderline/mixed**: K+2R 732cp (correct), K+3R -72cp (wrong sign), Q -17cp (too small) |
| 10.5M | Degenerate: K+2R -17cp, K+3R -65cp, Q -5cp |
| 14.04M (full) | Degenerate (see test 6 above) |

**Not a sharp cliff — a gradual degradation zone somewhere between ~7M and
~10.5M rows**, with 8.75M already showing inconsistent/partial breakdown
(one extreme-position sign correct, others wrong). This is more informative
than a single threshold would have been: it rules out an off-by-one-style
bug at one specific row count and points instead toward something that
scales continuously with data volume — rather than a discrete switch.

### Watching it happen live: gradual erosion, not a sudden collapse — and a falsified hypothesis

Added per-epoch sanity-check printing directly to `nnue_train.py` (not just
a post-hoc check) and reran the full 14.04M dataset, watching the three
extreme-position evals epoch by epoch. The result was informative: **healthy
and strongly-signed through epoch ~20** (e.g. epoch 20: K+2R=1111, K+3R=1034,
-Q=-836 — all correct), then **visible, continuous erosion starting right
around the first LR decay (epoch 22)**, with magnitudes shrinking epoch over
epoch (K+2R: 1141 → 1063 → 621 → 550 → ... → 344 by epoch 36) and the -Q sign
flipping to small positive noise by epoch 26 — all while **validation loss
kept monotonically improving** the entire time (0.857 → 0.81). This
independently confirms the earlier note: val loss cannot detect this
failure mode at all, since it's dominated by the far more common
near-balanced positions.

The erosion pattern — gradual, starting after an LR decay, on rarely-
reinforced features — looked exactly like the signature of weight decay
being applied every optimizer step rather than every epoch: the 14M-row
dataset has ~4.5x more steps/epoch than the 3M sample that trained
correctly (3260 vs 732 at bs=4096), so the same nominal "60 epochs,
wd=0.001" applies ~4.5x more cumulative decay pressure on the large
dataset — which would disproportionately punish weights for rare features
(extreme material imbalances) that only get reinforced on the rare batches
containing them. This is a well-known pitfall for sparse/embedding
architectures under uniform weight decay, and it fit every observation.

**Tested directly and falsified.** Reran the reliably-broken 10.5M-row
config with `weight_decay=0` instead of `0.001` — if the hypothesis were
right, this should fix it outright. It didn't: K+2R=43cp, K+3R=-129cp (wrong
sign), Q=-15cp — the same degenerate collapse, weight decay entirely
removed. **The mechanism is not weight decay.** This was a well-reasoned,
mechanistically plausible explanation that a clean, direct experiment ruled
out — worth recording exactly because it closes off a plausible-looking
dead end for whoever picks this up next, rather than leaving it as an
untested "probably this" in the priority list.

### Step count also falsified, then the real mechanism found: hidden-layer capacity

Two more tests, prompted by a good question from the user ("could FICS data
quality — junior/blundered games — be the issue?"). That specific framing
doesn't fit (junk-proportion is identical between the 3M and 14M samples,
since both are random draws from the same shuffled population — a
proportional-quality problem can't create a row-count-specific cliff), but
it pointed at the right neighborhood: **diversity**, not proportion.

**Step count, tested directly and falsified.** Took the 3M-row sample that
trains correctly at 60 epochs (~732 steps/epoch) and ran it for 267 epochs
instead — matching the full 14M/60-epoch run's total optimizer step count
(~195,600) exactly, but on the same 3M *unique* rows repeated many more
times. If total steps were the cause, this should collapse just like the
big run did. **It didn't** — healthy and correctly-signed through all 267
epochs, right through the same relative LR-decay point, ending at K+2R=1594,
K+3R=1309, both strong and correctly signed at the very last epoch. This
rules out step count / repetition entirely: the large dataset's problem is
specifically about the number of *unique* rows, not how many gradient
updates happen.

**Hidden-layer width (`HID`), tested directly, and this is the real
mechanism.** With more unique rows, the network sees far more *distinct*
noisy/unusual patterns (blunders, rare structures, weird tactics from every
skill level in the FICS pool) — a diversity effect, not a volume effect.
Our hidden layer was only `HID=32` wide. Reran the reliably-broken 10.5M-row
config with `HID=128` (4x wider) instead — **the sign-flip collapse
disappeared entirely**. All 60 epochs stayed correctly signed (no wrong
signs anywhere in the run), e.g. final epoch: K+2R=424, K+3R=409, Q=-113.
There's still gradual magnitude erosion over the run (peak ~1400 early on,
down to ~400-600 by the end) — so widening the hidden layer doesn't
perfectly eliminate the underlying effect, but it keeps the network in a
"correctly-signed, still-useful" regime instead of collapsing into
near-zero/wrong-sign garbage. This is a real, validated fix (or at minimum a
major, confirmed mitigation): **the original `HID=32` was simply too narrow
to hold a clean signal once the unique-pattern diversity got large enough**
— a straightforward capacity bottleneck, not a training-dynamics bug.

### Full-scale HID sweep: HID=128 is the right answer for this dataset, HID=256 is not

Followed up properly rather than assuming bigger is strictly better (a jump
to HID=256 on the full 14M set was tried first and looked worse — see below
— which broke the session's own one-variable-at-a-time discipline right
when it mattered; caught and corrected on direct pushback rather than
handed off half-finished):

| Config | Result at epoch 60 (final) |
|--------|------------------------------|
| Full 14M, HID=256 | Degenerate/chaotic: K+2R oscillating incl. negative, K+3R strongly wrong-signed (~-1300 to -1550 from epoch 40 on) — *worse* than HID=128, not better |
| Full 14M, HID=128, 60 epochs (val-loss-selected checkpoint) | Partially degraded: K+3R=523 and Q=-597 correct, but **K+2R=-471 wrong sign** — better than HID=32 (total collapse) and HID=256 (chaotic), but not clean |
| Full 14M, HID=128, **stopped at epoch 22** (before val-loss-driven late-epoch erosion sets in) | **All three correct and strong**: K+2R=779, K+3R=653, Q=-970 |

Two real, non-obvious findings here: (1) capacity requirements are **not
monotonic** with hidden-layer width — HID=256 did worse than HID=128 on the
identical full dataset, so "just make it bigger" is not a safe assumption
and needs its own sweep, not a single jump; (2) **validation loss actively
selects a worse checkpoint over long full-scale runs** — it kept improving
monotonically through all 60 epochs while the sanity checks visibly
degraded from ~epoch 22 onward, so the standard "save whenever val
improves" checkpointing silently throws away the best real net in favor of
a later, sanity-degraded one. Stopping training early (epoch 22, right
before the erosion trend starts) recovered a genuinely clean, strongly and
correctly signed net where letting it run to completion did not.

**This net (`nnue_hid128_early.bin`, HID=128, 22 epochs, full 14.04M
dataset) is the healthiest full-scale net of the entire session by every
static sanity check** — and it was tested in real match play regardless of
that: **0/18 at blend=100 and 0/14 at blend=20 vs Vice**, both a complete
shutout, while classical eval alone scored 27-30% in the same window on the
same machine. So the conclusion holds even for the best net produced
tonight: **passing the extreme-material sanity check is necessary but not
sufficient.** The net can now correctly recognize gross material advantages
it previously got wrong, but real chess strength lives in subtler
middlegame judgment — pawn structure, piece coordination, king safety
nuance — that these sanity-check positions never exercise, and that gap
appears to be independent of the collapse mechanism investigated all
session. Fixing the collapse was real, necessary, and worth doing — it just
wasn't the thing standing between this NNUE pipeline and beating classical
eval.

### Acted on that conclusion directly: 6x more Crafty data, same result

Followed the priority list's own top recommendation rather than stopping at
a diagnosis: scaled Crafty-labeled data from ~40k to ~240k (a second
parallel 8-process batch, ~199,566 positions in a few hours of wall-clock
Crafty time), combined into a new 14.24M-position dataset, and retrained
with the now-validated recipe (`HID=128`, stopped in the healthy window
before val-loss-driven erosion — epoch 26 this time, chosen by watching the
live per-epoch sanity output rather than guessing).

**Result: the cleanest sanity check of the entire session** — K+2R=1445,
K+3R=1407, Q=-484, all strongly and correctly signed, matching the Python
float model closely, healthy through the entire trajectory up to the point
training was stopped (no erosion visible at all before epoch 26, unlike
every previous run). **And still 0/18 (blend=100) and 0/14 (blend=15) vs
Vice** — no different from every other net tonight, despite being provably
the best-behaved by every measure available.

This is a meaningful negative result, not a non-result: it shows 240k
Crafty-quality positions (still only ~1.7% of the 14.24M total) isn't yet
enough to shift real playing strength, even though the pipeline, training
stability, and architecture are all now demonstrably sound. Either the
Crafty fraction needs to go up by another order of magnitude or more
(genuinely more Crafty wall-clock time, likely a full day+ at this
throughput), or — more likely, given the sanity checks say the net
correctly understands material while still losing every game — the
remaining gap really is in positional judgment that no amount of *this
kind* of labeling (single-position eval snapshots) teaches, and the
priority list's suggestion of a proper positional validation signal
(a small held-out puzzle-style suite) matters more than more data volume
at this point.

### Confirmed directly, not just inferred: NNUE's positional judgment is the real gap

Rather than leave "the gap is probably positional judgment" as an inference
from match losses, tested it directly using the repo's existing Strategic
Test Suite files (`suites/STS1.epd`-`STS15.epd`, 1486 positions total) —
these test *positional/strategic* understanding specifically, unlike WAC's
tactics-only puzzles, via `bin/experion epdtest`.

| Config | STS solve rate |
|--------|-----------------|
| Classical eval | 482/1486 (32.4%) |
| NNUE blend=5 (`nnue_v13_early.bin`) | 342/1486 (23.0%) |
| NNUE blend=15 | 325/1486 (21.9%) |
| Pure NNUE (blend=100, the best/cleanest net of the session) | **101/1486 (6.8%)** |

Added an `EXPERION_BLEND` env override (`src/experion.cr`) so blend could be
swept via `epdtest` directly, since that tool doesn't go through the UCI
`setoption` path the way match testing does.

Nearly a 5x gap at blend=100, measured directly rather than inferred from
won/lost games — and critically, **the degradation is monotonic with blend
percentage and there is no sweet spot**: even blend=5, the lightest level
tested, is still meaningfully worse than pure classical (23.0% vs 32.4%).
Every amount of this net's influence hurts positional judgment; the earlier
match-play finding that blending never helped (0% at both 15% and 100%
blend vs Vice) has a direct, quantified, non-match-noise explanation here.

This is the clearest, most direct evidence in the whole session for *why*
every net lost every match despite passing every material sanity check: the
sanity checks (K+2R vs K, etc.) only test whether the net can count
material, which it now does correctly — they say nothing about strategic
judgment (pawn structure, piece activity, weak squares, outposts — exactly
what STS tests), and on that axis the net is dramatically behind classical
eval, not just slightly. This reframes the priority list's "build a
positional validation suite" item from a *proposed* next step to something
already available and already measured — the STS suites already in this
repo are that suite. Any future net should be checked against STS solve
rate (with `EXPERION_BLEND` to sweep blend percentages cheaply, no
retraining needed) before any match testing, the same way the extreme-
material sanity checks are — it's a two-minute check that would have made
this specific gap visible many training runs earlier.

### Tested "quality over quantity" directly — also negative, and informative

One more specific, cheap hypothesis worth testing before concluding: is the
positional-judgment gap caused by self-play noise *diluting* the good
Crafty labels within the 14M-row mixed dataset? If so, training on the
~239k Crafty-labeled positions **alone** — 60x less data, but zero
self-play dilution — should do measurably better on STS than the mixed
dataset did, even if raw sanity-check magnitudes are noisier from less
volume.

**Result: worse, not better.** Pure-Crafty training (`nnue_crafty_pure.bin`,
239,474 positions, HID=64) scored **83/1486 (5.6%) on STS** — slightly
*below* the mixed 14M-dataset net's 6.8%, despite Crafty being the
theoretically stronger label source with zero dilution. (Sanity check was
also mixed: K+2R=273 and K+3R=1018 correctly signed, but Q=1124 — wrong
sign on the queen-imbalance case again, a pattern that has now recurred
across several unrelated nets this session and may itself be worth a
dedicated look — possibly under-coverage of "one side already lost the
queen" positions in constructed/search-derived data generally.)

This directly disproves "self-play dilution" as the explanation and points
somewhere more fundamental: it isn't *which* label source feeds this
architecture, quality or quantity — something about the architecture's
capacity to represent positional concepts is the actual ceiling. That
lands squarely back on the biggest structural gap flagged early in this
document (Part 1): our HalfKA features are a flat, king-position-agnostic
768-per-side board representation, while real NNUE architectures use
king-relative feature buckets specifically because positional value is
highly conditional on king position (a knight's value on a given square
depends heavily on where the king castled) — information this
architecture's *inputs* simply don't carry, no matter how good the labels
are or how the hidden layer is sized. Fixing that is a real feature-set
redesign (multiplies feature count by however many king buckets, with a
correspondingly larger data requirement), not another training-recipe
tweak — the next legitimate escalation after everything ruled out
tonight, not something to attempt casually.

### A real, separate classical-eval bug found from watching an actual lost game

Not NNUE-related. Reviewing a lost game's PGN showed Experion evaluating
itself as comfortably ahead (+6 to +8) for many moves, then walking directly
into a losing forced king-hunt — and correctly recognizing "-M8" only once
the mate was already unavoidable. That pattern (correct once forced, blind
before) pointed at the king-safety term itself, not search depth.

Found it in `eval.cr`'s "king attack pressure" section: for each color, it
computed `ksq_att = pos.king_sq({{color}})` — that color's **own** king —
and then added a bonus to that same color for its own pieces being near/
attacking the zone around **its own king**. The established codebase pattern
for "opponent" everywhere else in this file is `{{color}} ^ 1`. This is
almost certainly a copy-paste-order bug: the code rewards a side for merely
having pieces near its own king (a `mystery-buff`, not a threat signal), and
never computes or penalizes the opponent's actual attacking pressure against
that king at all. Fixed to `pos.king_sq({{color}} ^ 1)`. WAC solve rate
unchanged (145/300 — expected, WAC is tactics-only and doesn't exercise
positional king safety), and a small match sample (2-9 vs Vice, 18.2%) showed
no clear swing either way — the sample is too small to confirm the fix's
real-game impact, but the code-level reasoning is solid independent of match
noise, and it should be kept.

## Part 3: King-relative feature buckets — implemented correctly, training failed twice

Acted on Part 2's top recommendation (real king-relative feature buckets,
motivated by the confirmed positional-judgment gap: 32.4% classical vs 6.8%
pure NNUE on STS). Implementation:

- `tools/nnue_train.py`: `fen_features()` now computes each perspective's own
  king-file bucket and offsets ALL of that perspective's feature indices by
  `bucket * FEATURES_PER_BUCKET` (1536). Export format bumped to "ENN3"
  (adds a `KING_BUCKETS` header field).
- `src/experion/nnue.cr`: `feature_index()` takes a bucket parameter,
  `refresh()` computes both kings' buckets before rebuilding, `w1` sized
  dynamically from the file header (`FEATURES_PER_BUCKET * KING_BUCKETS`).
- `src/experion/search.cr`: `push_acc` — the critical incremental-update
  subtlety. Because a perspective's own king square now selects its entire
  feature block, moving that king changes EVERY feature index for that
  perspective, not just the king's own (unlike the flat scheme, where only
  castling needed a special case for its 3-piece move). Any king move (not
  just castling) now triggers `Nnue.refresh` for the whole accumulator row.
- `tools/nnue_check.py`: new tool — a pure-Python integer-exact
  reimplementation of the engine's eval pipeline that reads the raw `.bin`
  file directly (not the training-time float model), so it catches
  format/quantization bugs a float-vs-float comparison would miss.

**Correctness is verified, twice, independently of net quality.** For both
a 4-bucket and a 2-bucket build, `tools/nnue_check.py`'s output matched
`bin/experion`'s `eval` command (`EXPERION_NNUE=... EXPERION_BLEND=100`)
bit-for-bit cp value on every test FEN. The Crystal engine's king-bucket
implementation is correct.

**Both training attempts nonetheless produced unusable nets.**

- **4 buckets** (file quadrant: a-b/c-d/e-f/g-h), 30 epochs, same 14.04M-row
  `training_final.txt` / `HID=128` recipe that worked for the flat net.
  Sanity checks oscillated with wrong signs from epoch 6 on, "recovered" a
  few times, then the val-loss-selected checkpoint (epoch 29) was wrong-
  signed on K+2R and K+3R. Match-tested directly (this is the real test,
  not the sanity proxy): **0-40 vs Vice at pure NNUE (`EvalBlend=100`) —
  mated every single game.** Diluted to `EvalBlend=20` (80% classical): still
  **1-39, -636 Elo** — the net is actively harmful even as a fifth of the
  blend, not just neutral.
- **2 buckets** (kingside e-h vs queenside a-d), same recipe, to test
  whether 4-way data splitting (quartering effective per-bucket data with no
  increase in real data) was the cause. It was not fixable this way: the
  2-bucket run showed the SAME failure signature, if anything more
  consistently wrong (K+2R and K+3R wrong-signed for essentially the entire
  back half of training, epoch 19 through 30, while val loss kept smoothly
  improving the whole time — 0.7505 → 0.7335). This **falsifies the
  per-bucket-data-starvation hypothesis**: halving the split didn't help.

**Revised leading hypothesis (untested):** the LR schedule (peak lr=0.003,
step decay ~epoch 18-19, from `nnue_train.py`) was tuned against the flat,
single-bucket net's 1536-row embedding. Any king-bucketed embedding (2x or
4x more input rows, each seeing proportionally less signal per optimizer
step at a fixed batch size) may simply need a different LR/warmup — lower
peak LR and/or longer warmup — not yet tried. The fact that going from 4→2
buckets didn't help, but didn't make it categorically worse either, is more
consistent with "the schedule is wrong for any bucketed embedding" than
with "buckets are fundamentally the wrong idea" — but this is a hypothesis
for the next session, not a conclusion.

**A third attempt tested the LR-schedule hypothesis directly and it did
not hold up.** Retrained the 2-bucket architecture with peak lr=0.0012
(2.5x lower than the 0.003 used everywhere else), otherwise identical
(same 14.04M rows, HID=128, 30 epochs). Result was *partially* different —
K+2R was now consistently correctly-signed and reasonably strong (epoch
25-29: 126→237, final export 194cp on the standalone sanity FEN) — but
K+3R and -Q stayed wrong-signed the whole time (K+3R: -54 to -264; -Q:
+55 to +103, should be negative). Match-tested anyway per this project's
own rule (match results over proxy metrics): **0-17-0 through 17 games vs
Vice at pure NNUE** — the same total-collapse signature as the original
4-bucket net, not meaningfully better. **This falsifies "it's just the LR
schedule"** as a sufficient explanation — a 2.5x lower peak LR fixed one
of three sanity axes but didn't rescue actual play at all. Something more
fundamental about how the king-bucket feature split interacts with this
data/architecture is still wrong, not yet identified.

**Do not ship or use `nnue_kingbucket.bin` (4-bucket), `nnue_kingbucket2.bin`
(2-bucket), or `nnue_kingbucket2_lowlr.bin` (2-bucket, lower LR).** All
three are worse than doing nothing when tested in real games.
`nnue_hid128_early.bin` (the flat, non-bucketed net, HID=128, stopped at
epoch 22 — see Part 2) remains this session's only NNUE checkpoint that
didn't actively lose games when tested, though it still lost to classical
eval overall on STS-style positional measures. **Recommendation for a
future session: king-relative feature buckets need more fundamental
investigation before another training attempt** — e.g. checking whether
the bucket split is somehow scrambling the shared "material count" signal
that both flat-net sanity checks and real games depend on most heavily
(the near-total collapse in real games despite a Crystal/Python bit-for-bit
correctness match suggests the FEATURE DESIGN itself, not the training
recipe, may need reconsideration — e.g. does splitting on king file
actually give the net enough of a "this piece near this edge is
differently valuable" signal, or does it just make an already-hard
learning problem harder without a corresponding benefit at this data
scale). This is not a training-recipe problem to keep iterating on with
LR/epoch tweaks; it needs fresh architectural thinking.

## Part 4: First direct Experion-vs-Crafty match result this session

Every earlier "vs Crafty" figure in this document (e.g. the ~4% in the
TL;DR) was inferred from STS/WAC-style proxy scores or small mixed samples,
never a dedicated head-to-head match. Ran one directly: classical eval only
(no NNUE), current `main`, `10+0.1`, `THREADS=1`, `CONC=1`, vs Crafty 25.2
via the XBoard bridge (`tools/match/run_match.sh 10+0.1 25 crafty`).

**Final result over all 50 games: 2 wins - 47 losses - 1 draw (5.0%).**
Consistent with the ~4% figure already in the TL;DR — this corroborates
rather than changes the picture, but it's now a real, complete match
result, not an inference. Several losses were by direct mate, not just
material grind, suggesting search depth/tactical horizon at this time
control (not just positional eval quality) is part of the gap to a
3041-rated engine.
**Current honest status: classical Experion does not beat Crafty (5.0% in
a 50-game sample), and no NNUE variant produced this session has closed
that gap — all three king-bucket nets tested are actively worse than
classical alone.**

## Recommended next steps, in priority order

**Updated after Part 3/4.** King-relative feature buckets were the top
recommendation from the previous pass and were implemented correctly (bit-
for-bit verified) but failed to train usefully twice (4-bucket and
2-bucket, both actively harmful in match play — see Part 3). Given a real
Crafty match result now exists (Part 4: 4.5%, classical eval only) and NNUE
has not yet produced a single net that helps in real games this entire
session, the honest next-step ordering is:

0. ~~Try a lower peak LR on the 2-bucket architecture~~ — **done and
   falsified.** lr=0.0012 (2.5x lower) partially fixed one of three sanity
   axes (K+2R) but the net still totally collapsed in real play (0-6-0 vs
   Vice, same signature as the un-tuned runs). The problem is not simply
   an LR/warmup mismatch for the larger embedding. Before attempting king
   buckets a fourth time, the feature design itself needs fresh scrutiny
   (see Part 3's closing paragraph) — more LR/epoch/schedule tweaking on
   the same feature scheme is not expected to help based on this evidence.
1. **Consider that classical search/eval improvements may be higher-value
   right now than more NNUE experiments.** Several of this session's
   Crafty losses were by direct mate, not slow material grind — that
   points at search depth/tactical horizon at match time controls, which
   NNUE (even a working one) would not fix. The lazy-SMP regression
   (item 6 below) alone, if fixed, could be real free Elo without touching
   NNUE at all.

The collapse mechanism from the pre-king-bucket (flat) net is now solved,
not just characterized: it's hidden-
layer capacity relative to dataset diversity (`HID=32` too narrow for
14M rows; `HID=128` works, `HID=256` does not — non-monotonic, needs its own
sweep, don't assume bigger is safer), compounded by validation-loss-driven
checkpoint selection silently picking a later, sanity-degraded epoch over an
earlier, genuinely good one. Both fixed/mitigated (use `HID=128` for this
data scale; stop training near the point sanity checks peak, not where val
loss is lowest). **But the best net this produced still didn't beat
classical eval in real play (0/18 vs Vice)** — so the actual priority has
shifted to a problem the collapse investigation was never going to solve:

1. **The net's real-game judgment ceiling, not its architecture or training
   stability.** A net with perfect sign/magnitude on extreme-material sanity
   checks still lost every game. That means the gap is in ordinary
   middlegame positional understanding — exactly what a K+2R-vs-K check
   can't measure. Concrete directions: (a) revisit label circularity in
   earnest now that training itself is stable — scale up Crafty-labeled data
   well beyond the ~40k tested (see priority 2 below), since that's the only
   labels-from-a-stronger-source data tested so far; (b) build a genuinely
   informative validation signal beyond both raw val loss and the three
   extreme-position sanity checks — e.g. a small held-out set of real
   middlegame positions with known-good moves (a mini puzzle suite) that
   would actually detect positional-quality regressions the current checks
   miss entirely; (c) consider that with training stability now solved,
   a proper architecture upgrade (real king-relative feature buckets,
   flagged in Part 1 as the biggest representational gap vs. real NNUE
   engines) may finally be worth the engineering cost, since it's no longer
   fighting an unstable training pipeline at the same time.
2. **Systematically find the right `HID` for future dataset sizes, not just
   this one.** The 128-good/256-bad result was one data point at one scale;
   don't assume HID=128 is universal as the dataset grows further.
3. **Use per-epoch sanity tracking (now built into `nnue_train.py`) to pick
   checkpoints, not just val loss.** Either stop training near the observed
   sanity peak (as done for the epoch-22 net) or track a combined
   sanity-based checkpoint metric alongside val loss — don't let a long
   run's "best val loss" checkpoint silently be its worst real net.
4. **Get much more Crafty-labeled (or otherwise stronger-than-our-classical)
   data.** ~40k positions in ~35-40 minutes across 8 processes is a real but
   small start toward addressing the label-circularity ceiling (self-play
   labels bounded by our own classical eval) — likely the actual remaining
   bottleneck now that training stability is solved. Scaling to 500k-1M
   would take on the order of 6-12 hours of wall-clock Crafty time — budget
   for it explicitly.
5. **Diversify self-play move selection** away from uniform-random walks —
   play with the engine's own shallow search (with randomness for diversity)
   so generated positions look like real chess.
6. **Diagnose the lazy-SMP regression.** Not NNUE-related, but likely worth
   real Elo "for free" once understood — TT-pollution was ruled out, cause
   unknown.
7. Consider `torch.nn.EmbeddingBag(mode='sum')` for a further CUDA training
   speedup — not yet measured, lower priority than the above.
8. The king-safety `^ 1` fix (Part 2) needs a real (30-40+ game) match sample
   to confirm its practical impact — the sample taken tonight was too small.

## Validation protocol (apply before trusting any new net or match result)

Learned the hard way this session — small samples and untested assumptions
repeatedly produced misleading conclusions:

- **Always sanity-check eval magnitude on extreme positions before any match
  testing.** K+2 Rooks vs bare King, a position down a full queen, and a
  couple of normal early-opening positions. This is free (seconds) and would
  have caught three of the five bugs above immediately instead of after hours
  of confused match testing.
- **Verify config actually applied.** The EvalBlend bug went undetected for a
  long stretch because nothing checked whether the intended blend was really
  in effect — check fastchess's own stderr for `Warning; ... doesn't have
  option ...` after any new `setoption`-based match config.
- **Use CONC=1 (no concurrency) for anything you intend to compare.** Running
  two simultaneous real-time games (CONC=2+) means they compete for CPU,
  which measurably corrupts time-based play quality — comparisons across
  different CONC settings are not valid.
- **Match samples need to be large.** 10-16 game samples at this project's
  current Elo gaps swing from ~6% to ~24% for the *identical* configuration.
  Treat anything under ~30-40 games as a rough direction, not a conclusion.
- **Change one thing at a time, even under time pressure.** The final run of
  this session combined a new architecture, a loss-function fix, and an
  order-of-magnitude data change in one shot. It regressed, and there is no
  way to tell which of the three changes (or which interaction between them)
  caused it. Every other finding in this document came from isolating a
  single variable — the one time that discipline was dropped, under the
  pressure of a long session, is the one time the result was uninterpretable.

## Part 5: search-first plan (see `~/.claude/plans/iridescent-roaming-plum.md`) — Phase 1 succeeded, Phase 2 (first attempt) reverted

Following the NNUE dead-ends above (three king-bucket attempts, all
unusable) and a direct 50-game classical-eval Crafty result (2-47-1, 5.0%),
a follow-up session planned a search-first approach instead: fix the known
lazy-SMP regression, then improve search efficiency, gated by ladder tests
at every step (see the plan file for full context and the PGN-diagnosed
depth-7-9 tactical-miss evidence that motivated this direction).

**Phase 1 (SMP fix): real success.** Found and fixed a genuine data race —
`TT#@age` was a plain `UInt8` bumped from every thread with no
synchronization in `think_smp`'s shared-TT path, corrupting the
replacement-policy check and even risking corrupting packed TT entry bits
if it ever exceeded the field's 6-bit range. Fixed via `Atomic(UInt8)` in
`src/experion/tt.cr`. Result: Threads=4 went from catastrophic collapse
(0/40, 0/17, 0/19, 0/7 across multiple prior tests) to parity-or-slightly-
ahead of Threads=1 across the full ladder (Vice 18.3% vs 17.5%; Crafty
6.2% vs 5.0%). New CLI diagnostic tool added: `bin/experion smpdiag
<threads> <movetime_ms> [fen]` measures the primary thread's real nodes/
depth/nps solo vs concurrent — useful for any future SMP work on this or
other hardware. `run_match.sh`'s `THREADS` default updated from 1 to 4 to
reflect the validated fix.

**Phase 2 (time management, first attempt): regressed, reverted.** Added
an "instability extension" to `search.cr`'s iterative-deepening loop — when
the root best move changes between completed iterations, extend the
effective soft time budget by 1.5x (capped at `hard_ms`) rather than
cutting off. Ladder-tested at Threads=4 vs Vice, 30 games: **2-27-1
(8.3%)**, clearly worse than the Phase 1 baseline (18.3%) at the same
sample size. **Reverted cleanly** (removed the `soft_budget` tracking,
restored the plain `limits.soft_ms` check) — `crystal spec` (645 tests)
confirmed green both before and after. Left as a negative result rather
than iterated on further, per this doc's own "change one thing, verify,
move on" discipline and this session's time budget.

**Hypothesis for why it regressed** (untested, for a future attempt): the
1.5x multiplier compounds on every instability event within a single
move's search with no cap on how many times it can trigger, and — more
importantly — the extension only looks at `hard_ms` for that one move's
ceiling, not at total remaining game clock (`my_time`). Over a full game,
moves that repeatedly trigger the extension could accumulate real clock
pressure later in the game even without any single move timing out,
degrading play in the middlegame/endgame in a way a single-move sanity
check wouldn't catch. A future attempt should either cap the number of
extensions per move, use a smaller multiplier (e.g. 1.2x), or track
cumulative time spent this game against a fraction of `my_time` before
granting the extension — and should ladder-test with enough games (30+,
per this doc's own established sample-size lesson) before trusting a
result either way.

**Status at time of writing**: Phase 1's SMP fix is real, validated, and
kept. Phase 2 is back at its pre-attempt state (plain time allocation,
unchanged from before this session). NNUE remains out of scope per the
plan. Next candidate step per the plan: search/pruning efficiency (LMR,
null-move margins, quiescence) informed by the same PGN-diagnosed
tactical-miss example, rather than another time-management variant.

### TT/history staleness: a real finding, not chased further this session

Tried to reproduce the diagnosed depth-7-9 tactical-miss game exactly by
replaying it move-by-move through a live UCI session (`position` + `go
movetime 575` repeated for all 24 half-moves leading to the critical
position, so TT/killers/history accumulate exactly as in a real game) —
**this did NOT reproduce the original blunder**; the faithful replay
picked the safe `e1d1` at the same nominal depth (8) where the real game
picked the losing `e1f1`. A "cold" one-shot `position + go depth 8` on the
same final position also picked the safe move. Both point to the same
conclusion: **real-time-budget search has genuine run-to-run variance**
(wall-clock cutoffs land at slightly different points in the search tree
depending on OS scheduling/timing jitter, which cascades into different
TT population and move choices) — this specific historical game is not a
reliably reproducible regression test case, and single-anecdote PGN
diagnosis has a real limit: it can point at a *category* of weakness
(shallow-depth tactical misses at fast TCs, confirmed) but not pin down
one deterministic bug to fix. Not chased further — flagged for whoever
picks this up next, since it explains why a single "grep the PGN for one
bad move" approach won't fully explain or fix the Crafty gap.

### New infrastructure: `tools/match/sprt.sh` — proper statistical testing for future tuning

Built after directly hitting the exact problem this doc's own "match
samples need to be large" lesson warns about: Phase 2's time-management
change was accepted-then-reverted based on a single 30-game fixed sample,
which is far short of what's needed to trust a small effect. fastchess
has built-in SPRT (`-sprt elo0=... elo1=... alpha=... beta=...`) — a
proper sequential test that keeps playing until the result is
statistically decisive rather than committing to one arbitrary sample
size. `tools/match/sprt.sh` wraps this as a **self-play A/B test**:
`bin/experion` (candidate) vs `bin/experion_baseline` (last validated
build) — this is the standard way real engine projects validate changes,
and is more sensitive than testing each build separately against a
third-party ladder opponent. Usage: `cp bin/experion bin/experion_baseline`
before a change, make the change, rebuild, then `zsh tools/match/sprt.sh
<tc> <elo0> <elo1>`.

**Lesson learned running it once**: `elo0=0 elo1=5` (a tight band, used
for the NMP test below) converges far too slowly to be practical within a
single session at ~5-8 min/game — only 10 games completed before this
session's time ran out, nowhere near SPRT's own decision threshold. **Use
a wider band (`elo0=0 elo1=15` or `20`) for fast initial iteration**, and
reserve a tight band like `0/5` for confirming a change that already
looks clearly promising and is worth the long confirmation run (potentially
run overnight/unattended in a future session, not mid-session).

**First (informal, not SPRT-concluded) result — eval-scaled null-move
pruning.** Added `r += Math.min((static_eval - b) // 200, 3)` to the NMP
reduction formula in `search.cr` (reduce further when the null-move's
static eval clears beta by more, a standard technique in strong engines).
Ran the SPRT harness for 10 games before stopping it for time: **5-3-2
(60%)**, with every intermediate checkpoint (57%, 62.5%, 61%, 60%)
staying above 50% — consistent, never dipping to break-even or below, but
far short of formal significance. Made the pragmatic call to **keep it**
(snapshotted as the new `bin/experion_baseline`) given the consistent
directionality, `crystal spec` staying green, and the change being a
well-established technique rather than a speculative one — but this is
explicitly **not proven**, only directionally suggestive. A future
session should either let `sprt.sh` run to a real conclusion on this
exact change (confirm or revert it properly) or treat it as one of
several small changes to validate together once there's a longer stretch
of unattended compute time available.

**Correction, same session**: caught a real methodology mistake right
after writing the above — `bin/experion_baseline` had already been
overwritten with the NMP-included build before the wider SPRT run was
launched, meaning "candidate vs baseline" was briefly testing the engine
against an identical copy of itself (a coin flip by construction, not
a real test). Caught it, rebuilt a genuinely clean pre-NMP
`bin/experion_baseline` (temporarily stripped the NMP lines from
`search.cr`, rebuilt, snapshotted, restored the NMP version as
`bin/experion`), and relaunched properly with a wider band
(`elo0=0 elo1=20`, expected to converge much faster than the earlier
`0/5` attempt) — see "Current repo state & how to resume work" below for
whether this run concluded before the session ended and what the binaries
on disk actually represent right now.

## Current repo state & how to resume work

**Written at the end of this session — read this first if picking the
work back up.**

### Binaries on disk right now
- `bin/experion` and `bin/experion_baseline` are IDENTICAL as of the end
  of this session: both have the Phase 1 SMP fix (`tt.cr` @age atomicity)
  AND the NMP eval-scaled reduction (`search.cr`). NNUE code is present
  but inert unless `EXPERION_NNUE` is set.
- **The corrected wide-band SPRT test (`elo0=0 elo1=20`,
  `/tmp/sprt_nmp_wide.log`) was stopped for time before reaching a formal
  verdict**, at **7-3-2 over 12 games (66.7%)**. Every intermediate
  checkpoint from game 4 onward stayed at or above 60% (never dipped to
  break-even), which is a meaningfully more consistent signal than the
  earlier tainted 10-game test, though still short of SPRT's own
  significance threshold. **Made the pragmatic call to keep the NMP
  change** — `bin/experion_baseline` was re-synced to match `bin/experion`
  (`cp bin/experion bin/experion_baseline`) after stopping the test. If
  you want to actually settle this with statistical confidence rather
  than a judgment call, the cleanest path is: rebuild a genuinely clean
  pre-NMP binary again (temporarily strip the `r += Math.min((static_eval
  - b) // 200, 3)` line from `search.cr`, rebuild, save as a NEW file like
  `bin/experion_prenmp` so you don't lose it this time), and run
  `sprt.sh` against that, ideally for an extended unattended stretch
  (hours, not the ~15 minutes this session had budget for).

### Uncommitted changes (as of this writing)
`git status --short` shows modified: `src/experion/nnue.cr`,
`src/experion/search.cr`, `src/experion/tt.cr`, `src/experion_cli.cr`,
`tools/match/run_match.sh`, `tools/nnue_train.py`, plus untracked
`tools/match/sprt.sh` and `tools/nnue_check.py`. None of this has been
committed or pushed — per this project's earlier standing instruction
("don't push any games or big datasets, just core engine code... do this
along the way if there's significant progress"), the SMP fix in
particular is a strong, real, validated candidate for a commit — that's
the user's call, not something to do unilaterally.

### What to actually do next, in priority order
1. **Resolve/check the in-progress SPRT test** (above) — quick, just needs
   checking in on.
2. **If the NMP change is confirmed**: consider it a template for further
   search tuning — pick one more concrete, well-motivated change (LMR
   depth/move-count table, futility margins, quiescence delta pruning),
   SPRT it the same way with a wide band first, narrow the band only to
   confirm something that already looks clearly good.
3. **The TT/history staleness finding** (Part 5) is a real, unresolved,
   somewhat concerning observation (real-time search has enough run-to-run
   variance that a faithful game replay didn't even reproduce the original
   diagnosed blunder) — worth real investigation if there's appetite, but
   it's a deeper rabbit hole than a quick parameter tune.
4. **NNUE, if resumed**: needs either (a) an order-of-magnitude-plus more
   training data than the 14M rows used here, or (b) a fundamentally
   different feature design — not more LR/epoch/bucket-count tuning on
   king-relative buckets specifically, which is now three-for-three
   failed attempts. Consider first whether classical search improvements
   (which have a demonstrated, fast payoff this session) have more
   headroom before re-investing in NNUE's much longer feedback loop.
5. Diagnose and fix any remaining classical-eval weaknesses surfaced by
   repeating the PGN-diagnosis process (Part 4/5) on fresh Crafty match
   losses — a repeatable technique, not a one-off.
