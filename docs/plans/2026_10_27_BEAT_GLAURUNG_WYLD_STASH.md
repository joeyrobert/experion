# Experion milestone: score 67%+ against Glaurung 2.2, WyldChess 1.51 and Stash 21

## Implementation status

| Phase | What | Status |
| --- | --- | --- |
| 0 | Fair, working harness for all three opponents (native) | Not started |
| Prev | Beat Crafty 25.2 and Fruit 2.1 (previous milestone, the baseline) | Done |
| 1 | Baseline gauntlet (native, one thread each) incl. Fruit and Crafty reruns, plus a browser baseline | Not started |
| 2 | Search fixes and additions, each SPRT-gated | Not started |
| 3 | Self-generated training data and a new net | Not started |
| 4 | Time management and the browser build (SIMD, per-move limits) | Not started |
| 5 | Final confirmation gauntlet, ship net and binary, update README | Not started |

Repo: `/Users/joey/Repos/experion` (Crystal UCI engine). Read `CLAUDE.md`, `README.md` and `docs/TRAINING.md` first.

## Previous milestone (achieved): beat Crafty 25.2 and Fruit 2.1

This plan builds on the last milestone, which is done. These are the results recorded in the README:

| Opponent | Result | Score | Elo |
| --- | --- | --- | --- |
| Fruit 2.1 | 69-17-14 | 76% | +200 ± 74 |
| Crafty 25.2 (fair clocks) | 58-32-10 | 63% | +92 ± 68 |

That milestone is the baseline for this plan:
- Phase 1 reruns both matches with one thread on each side, which is this plan's measuring rule, and records the results as the starting point.
- Every phase from 2 on must keep Experion ahead of Fruit and Crafty. A change that gains against the new targets but loses ground against these two isn't accepted.
- The final confirmation (phase 5) includes the Fruit and Crafty matches again.

## Goal and definition of done

Experion must score **at least 67% against each of the three engines separately**: Glaurung 2.2, WyldChess 1.51 and Stash 21. A 67% score is about +123 Elo.

Done means all four of the following hold:

1. **Primary (native, fair):** 400 games per opponent at 10+0.1 using fastchess.
   - Both engines run on one thread with 64 MB hash.
   - Openings come from `tools/match/openings.pgn` in colour-swapped pairs.
   - Experion scores at least 67%, and the lower bound of the 95% interval is above +90 Elo.
2. **Long-TC check:** 200 games per opponent at 60+0.6 under the same settings. Experion scores at least 62%. Gains often shrink at longer time controls, so this guards against a bullet-only edge.
3. **Browser check:** the play page's tournament (or `tools/web_match.mjs` extended to these engines) at 1000 ms per move. Experion is first in a round robin of the four engines, and scores at least 60% against each. This is the setting where the user saw Experion lose, so it has to improve too.
4. **Baseline held:** Experion still beats Fruit 2.1 and Crafty 25.2 at one thread each side. Each gets 200 games at 10+0.1, and Experion must score at or above its phase 1 single-thread result, within error.

One thread on each side is the rule from here on. The Fruit and Crafty results above were measured with Experion on 4 threads against single-threaded opponents, which is worth roughly 50 to 100 Elo. The milestone still stands, but phase 1 re-measures it at one thread so every comparison in this plan is like for like. Never claim progress from a Threads=4 result.

## Where things stand

Reference CCRL ratings:

| Engine | CCRL Blitz | CCRL 40/15 | Eval |
| --- | --- | --- | --- |
| WyldChess 1.51 | ~2600 | ~2680 | HCE |
| Stash 21 | ~2710 | n/a | tuned HCE |
| Glaurung 2.2 | ~2820 | ~2910 | HCE |

- **Experion's estimate:** +200 against Fruit 2.1 (~2690) on 4 threads. That puts it around 2800 on a single thread, probably at or below Glaurung, with an unclear gap to Stash.
- **Native opponent binaries:**
  - `tools/match/ladder/glaurung22` and `tools/match/ladder/wyldchess151` already exist and are wired into `run_match.sh` as `glaurung` and `wyld`.
  - There is no native Stash. Build it from `third_party/stash-21/src` (its makefile; `make EXE=stash21` or similar) into `tools/match/ladder/stash21`, then add a `stash` case to `run_match.sh`.
- **The Glaurung harness is broken.** `tools/match/class_glaurung.log` shows 20-0 for Experion, but every game ended in "connection stalls" or "disconnects". Treat that result as void.
  - Glaurung answers `uci`/`isready`/`go` correctly when driven by hand.
  - Its default Threads value is 7, and it polls stdin during search.
  - Suspects, in order: the Threads option, the `Ponder`/`ponder` handling, and fastchess timeout settings. Fix this before any measurement.
- **Search state** (`src/experion/search.cr`):
  - Already present: PVS, TT, NMP, LMR, IIR, killers, history, countermoves, continuation history (`@conthist`), capture history (`@cap_hist`), RFP, futility, razoring, SEE pruning and aspiration windows.
  - Disabled by default because each measured as a loss (`EXPERION_DISABLE` defaults `chk,recap,sing,lmp`): singular extensions, LMP, check extensions and recapture extensions. In strong engines these are clear gains, so the implementations are probably wrong. That is likely the cheapest Elo in this plan.
  - No correction history.
- **Net:** ENN5, H=256, SCReLU, 8 king buckets and 8 output buckets. It was trained on CCRL 40/15 commented-PGN evals, with lambda 0.1.
  - The labels come from many engines at long time controls on positions those engines chose. They are noisy and limited to whatever CCRL games contain.
  - A net trained on the engine's own search scores is the standard next step.
- **Browser build:** `tools/build_wasm.sh` compiles without wasm SIMD. Each move runs in a fresh module instance with a 32 MB hash and no TT carried over. That handicap is the same for every engine on the page, but NNUE suffers more without SIMD than an HCE engine does.

## Hardware: a 2-core Ryzen 7 5700X machine

The agent runs on a machine with 2 cores of a Ryzen 7 5700X (Zen 3), not on the Mac where the earlier work happened. Plan every budget around that:

- **Setup:** the binaries under `tools/match/` and `/Users/joey/Repos/engines` are macOS arm64 builds and aren't in git, so nothing there carries over.
  - Build fastchess from source.
  - Build Fruit, Glaurung, WyldChess and Stash from `third_party/`.
  - Get Crafty 25.2 from its upstream source, for personal testing only; it is never redistributed.
  - Build `uci_bridge` from `tools/match/uci_bridge.cr`.
  - Point `run_match.sh` and `sprt.sh` at the new paths with env vars, not hardcoded `/Users/joey` paths.
- **Data:** the existing 142M-position CCRL dataset (`datasets/v5_full`, ~5 GB) isn't in git. Copy it over from the Mac, or re-extract it from the CCRL PGN with `tools/extract_ccrl_v5.py`.
- **Concurrency:** use 2 concurrent games everywhere. Without pondering each game keeps about one core busy, and SMT siblings make timing noisy, so don't go higher.
- **Testing throughput:** about 240 games/hour at 10+0.1, or about 480 games/hour at 5+0.05. A standard [0, 5] SPRT (5k to 20k games) would take days, so:
  - Run SPRTs at 5+0.05 with bounds elo0=0 elo1=10, which needs about 1.5k to 4k games, or 3 to 8 hours.
  - Use [0, 5] only for a change that [0, 10] can't decide and that looks worth the wait.
  - Batch related small changes into one SPRT when they're clearly independent.
- **Gauntlet cost:** about 5 hours for 400 games against each of the three targets at 10+0.1, about 12 hours for the 60+0.6 check, and about 2 hours for the Fruit and Crafty reruns.
- **Data generation:** about 450 positions/s on 2 Zen 3 cores, which is about 4 days for 150M positions. Use these targets instead:
  - 40M to 60M self-play positions per round (1 to 1.5 days), mixed with the existing CCRL data.
  - Never generate data while an SPRT or gauntlet is running.
- **Training:** PyTorch on 2 CPU cores manages roughly 10k positions/s (an estimate from the M5's 65k/s on 10 cores), so a 6-epoch run over ~200M positions takes about 1.5 days.
  - A GT 1030 with GDDR5 (not the DDR4 version) should be about 3 to 5 times faster, if the machine has one.
  - It needs a PyTorch build that still supports Pascal (sm_61). The CUDA 12.6 wheels do; check before installing a newer build.
  - It also needs a trainer change: stream batches from host RAM, because 2 GB of VRAM can't hold the dataset the way `train_v5.py` does now.
  - Without a GPU, cut epochs to 3 or 4 and train on 100M positions; the earlier runs showed validation loss levelling off early.
- **Order of work:** phase 2 (search, SPRT-bound) and phase 3 (data, CPU-bound) can't overlap on 2 cores. Do phase 2 first. Search gains also make the self-play data better, so the order helps the net too.

## Rules for the executing agent

- Judge only by match results; never use WAC/STS or validation loss to decide.
- Gate every engine change with SPRT against the previous baseline.
  - Command: `tools/match/sprt.sh` with `THREADS=1`.
  - Settings: elo0=0 elo1=10 for gains, and elo0=-10 elo1=0 for simplifications (see the hardware section for why).
  - Use 5+0.05 with 2 concurrent games.
  - Keep `bin/experion_baseline` updated after every accepted change.
- Run gauntlets against the three targets only at phase boundaries, not after every change. They're expensive, and tuning against the targets risks overfitting to them.
- `crystal spec` must stay green, and perft must stay exact.
- Follow the Crystal gotchas in `CLAUDE.md`. In particular, use `&+ &- &*` in hot loops.
- Log every result in this plan's results log (bottom), including rejected changes. Each entry needs the SPRT bounds, the game count and the Elo.
- Git:
  - Branches are named `joeyrobert/...`.
  - Open draft PRs against `main`.
  - Don't add Co-Authored-By lines to commits.
  - Never force push.
  - Never use em dashes.
- Pick a sensible default and carry on rather than stopping to ask.

## Phase 0: harness

1. **Build native Stash 21.**
   - Use the vendored source (Clang, `-O3 -march=native`) to build `tools/match/ladder/stash21`.
   - Add the `stash` case to `run_match.sh`, named with its CCRL rating, like the other cases.
2. **Fix Glaurung in fastchess.**
   - Try these first: `option.Threads=1`, `option.Ponder=false`, and a larger fastchess `timemargin`. Also check whether `-recover` is masking a crash.
   - Done when 20 games finish with no stalls or disconnects and no time forfeits.
3. **Add `tools/match/gauntlet.sh`.**
   - It runs Experion against glaurung, wyld and stash in sequence, then prints W-L-D, score and Elo ± error per opponent.
   - Arguments: tc, games per opponent and concurrency, with THREADS=1 and HASH=64 baked in.
   - It writes to separate PGNs, so the shared `games.pgn` stops growing.
4. **Check opponent health.**
   - Each opponent: 20 games at 10+0.1 against Fruit, with no forfeits or illegal moves.
   - Results should roughly match the CCRL ordering.

## Phase 1: baseline

1. Run `gauntlet.sh 10+0.1 400 2` and record the per-opponent score. This number is the bar the later phases move.
2. Rerun the previous milestone at one thread on each side: 200 games each against Fruit (`fruit`) and Crafty (`crafty`, through the XBoard bridge with fair clocks). These single-thread scores are the floor that later phases must not drop below.
3. Extend `tools/web_match.mjs` so `--opp` accepts stash, wyldchess and glaurung via their wasm builds in `site/engines/`.
   - Record a 1000 ms per move baseline over 96 games each.
4. Measure single-thread NPS for both builds, native and wasm, at the start position and on `bin/experion bench`. These numbers feed phase 4.

## Phase 2: search (SPRT each item, in this order)

Ordered by expected value per hour. Each change goes in alone, gets SPRT-tested, and is kept or reverted.

1. **Singular extensions, implemented correctly.**
   - Conditions: depth >= 7 (try 6 to 8), TT move, TT bound is lower or exact, and TT depth >= depth - 3. Excluded-move search at depth (depth - 1) / 2 with beta `tt_score - 2 * depth`.
   - Extend by one, or by two when far below beta (double extension, with a per-path cap).
   - Negative extension when `tt_score >= beta`, plus multi-cut return when the singular search fails high over beta.
   - Check that the excluded move is skipped in move generation order and is not written into the TT under the same key.
2. **LMP, again.**
   - Use the standard formula: quiet count limit `(3 + depth * depth) / (2 - improving)` at depth <= 8.
   - It applies only to quiets, never when in check, and only after a legal move has been found.
3. **Correction history.**
   - Store pawn-structure-keyed and material-keyed corrections of static eval, updated from `search_score - static_eval` when the bound allows.
   - This is a modern mainstay, usually +20 to 40 Elo.
4. **History-driven LMR:** reduce less for high history and more for low history (`history / 8192`), and reduce more at cut nodes and less at PV nodes.
5. **TT in quiescence:** probe in qsearch and store results with depth 0 or -1, if this isn't done already. Also try a TT cutoff in non-PV nodes at depth >= tt_depth.
6. **NMP tuning:** reduction `3 + depth / 3 + min((eval - beta) / 200, 3)`, plus verification search at high depth.
7. **Check extensions** in a limited form: only when SEE >= 0, or only at low depth. Retest them now that SE is fixed.
8. **Tune the margins with SPSA:**
   - Parameters: RFP margin, futility margin, LMR base and divisor, SEE thresholds, and the aspiration delta.
   - Expose them as UCI spin options under an `EXPERION_TUNE` build flag, and run fastchess SPSA or a small Python SPSA driver for 5k to 10k games at 5+0.05 (12 to 24 hours on 2 cores).
   - This step runs once the structural changes above have settled.

**Phase 2 exit:** run the gauntlet again at 400 games per opponent. Expect +60 to +120 Elo in total. If that falls short, look for a search bug before moving on:
- Cross-check node counts and best moves on a fixed-depth bench against expectations.
- Turn features off one at a time with `EXPERION_DISABLE`.

## Phase 3: data and net

The current labels are CCRL engine annotations. The next net should learn from Experion's own search scores and game results.

1. **Data generator.** Extend `gendata-selfplay`, or add `gendata-v5`, to produce data in the packed v5 format `tools/merge_v5.py` writes, or a text format the trainer accepts.
   - Play self-play games at a fixed node count: 5k nodes for most positions and 10k for a sample, with Threads=1 per game and 2 games in parallel.
   - Start each game with 8 random plies from the start position, or from a few plies of `openings.pgn` followed by random plies. Discard games where the score after the random plies is outside ±400.
   - Record the position, the search score from the side to move's point of view, and the final result.
   - Don't record positions where the side to move is in check, the best move is a capture or promotion, or the score is mate.
   - Adjudicate: a win at |score| > 2500 for 4 plies, a draw at |score| < 10 for 10 plies after move 40.
   - Target: 40M to 60M positions per round on the 2-core machine. Measure throughput first: at ~1M nps per Zen 3 core and 5k nodes, 2 cores give roughly 400 to 450 positions/s, so 50M takes about 1.4 days. Run it in the background with resume support (append and rotate files).
2. **Train on the target machine,** with plain `python tools/train_v5.py` (no torchrun) and `--device cpu`, or `cuda:0` if a GT 1030 is present (see the hardware section).
   - Mix the new self-play data with the existing CCRL dataset rather than training on self-play alone; the self-play set is too small on 2 cores to stand by itself.
   - Start from the shipped architecture (H=256) and lambda 0.1 to 0.3. Self-play scores are more consistent than CCRL scores, so retest lambda: try 0.1, 0.2 and 0.3.
   - Try mixing: self-play data alone, then self-play plus CCRL at 50/50.
   - Test H=384 and H=512 only once inference is fast. The earlier finding that width barely matters was on CCRL labels, so retest it with the new data at equal time.
3. **Gate each net** with SPRT against the shipped net via `EXPERION_NNUE=<path>`.
   - Ship a net only after it passes, and run `tools/check_v5.py` before shipping.
4. **Iterate:** regenerate data with the improved net. Two or three rounds is typical, and the gains shrink each round.

## Phase 4: time management and the browser build

1. **Time management:**
   - Make the soft limit depend on best-move stability (scale up when the best move changes, down when it holds for several iterations).
   - Also scale by node fraction spent on the best move.
   - SPRT at 10+0.1 and confirm at 60+0.6.
2. **Wasm SIMD:**
   - Build the browser binary with wasm simd128. Check whether Crystal's LLVM target accepts `--mattr=+simd128`, or pass the feature through `CRYSTAL_OPTS`/linker flags.
   - Check that the NNUE loops vectorize, using `wasm-objdump` and searching for `i16x8`/`i32x4` ops.
   - Measure the NPS gain in `tools/web_match.mjs`. All current browsers support SIMD.
3. **Browser search setup:**
   - Check that the play page uses the same search limits for Experion as for the other engines (movetime).
   - Check that Experion's wasm hash setting (32 MB) is sensible.
   - Don't give Experion an unfair advantage, such as a persistent instance that the other engines don't get.

## Phase 5: confirm and ship

1. Run the four definition-of-done checks above and paste the full tables into the results log.
2. Ship:
   - The net goes into `nets/experion.bin`.
   - Release build, with `crystal spec` and the perft suite passing.
   - Rebuild the wasm (`tools/build_wasm.sh`) and run `node tools/wasm_smoke.mjs`.
3. **Update the README strength section** with the new single-thread results against all three engines, and keep the Fruit and Crafty rows (rerun at one thread).
4. Draft PR against `main`, describing at a high level what changed and the measured result.

## Risks and fallbacks

- **A target is out of reach:** Glaurung 2.2 is the most likely to stay under 67%.
  - Run a separate 1000-game measurement to pin down the gap.
  - Spend the remaining effort on data volume (phase 3 at 300M+ positions) and SPSA, which are the most dependable sources of Elo.
- **Overfitting to the three opponents:** never tune against them directly. Keep using self-play SPRT, and use the gauntlets only to measure.
- **Self-play data looks bad:** if a self-play net loses to the CCRL net at equal data volume, check label sign and POV first (see the CCRL POV note in `docs/TRAINING.md`). A start position minus a rook must evaluate near -500.
- **Machine contention:** don't run data generation and SPRT at the same time; the timing noise ruins SPRT. With 2 cores there is no room to split them, so phases run one after another.

## Results log

| Date | Change | Test | Games | Result | Kept |
| --- | --- | --- | --- | --- | --- |
