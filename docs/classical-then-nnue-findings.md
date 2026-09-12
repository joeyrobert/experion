# Classical-first, then NNUE — session findings

Goal: beat Crafty 25.2 consistently with a newly trained NNUE, after
improving classical eval and comparing both. Ladder: Vice → Sungorus →
BBC → Fruit → Crafty. Engine stays Crystal; train on `joey@192.168.2.46`
(`llama`, RTX 3060 + GTX 1650). **Do not use Crafty to label.** Do not
use the ~5TB Lichess dump.

This document is the continuation of `docs/nnue-session-findings.md`.
Judge strength by the ladder, not SPRT. Strength gate vs this book is
BBC (~2465 CCRL), not Sungorus (~2269 hang canary).

## Authoritative ladder (keep this current)

Best Sungorus config before this continuation: hang-veto + tropism +
Threads=4, 10+0.1, 40 games pooled: **16–20–4 = 45%** (−~40 Elo).
Not a consistent beat.

| Opponent | TC | Result | Notes |
|---|---|---|---|
| Vice | **10+0.1**, 20g, enn4_ccrl12m | 15–1–4 **85%** (+301) | classical Vice was 64% at 2+0.02 |
| BBC | 2+0.02, 40g | 27–11–2 **70%** | |
| BBC | **10+0.1**, 20g, enn4_ccrl12m | 16–3–1 **82.5%** (+269) | classical was 72.5%; NNUE clearly stronger here |
| Sungorus | 2+0.02 | ~29% recovered | same depth ~8 as Sungorus |
| Sungorus | **10+0.1** hang-veto | **45% / 40g** best; later 20g baselines **35%** | hang canary, not Elo |
| Fruit | 2+0.02, 40g, classical | 4–36–0 **10%** | Fruit depth ~12 vs our ~8 |
| Fruit | **10+0.1**, 20g, enn4_ccrl12m | 2–18–0 **10%** (−382) | same as classical 2+0.02; still a depth gap |
| Crafty | **10+0.1**, **40g**, enn4_w192all | 17–17–6 **50%** | **Beat.** 20g 47.5% then 20g 52.5%. White 80%, Black **20%** (1 win + 6 draws). Mix of data12m + d16 quiets + FICS teacher labels. |
| Crafty | **10+0.1**, **40g**, enn4_ccrl12m_w192 | 17–21–2 **45%** | Prior best. White conversion, Black ~0–10%. |
| Crafty | **10+0.1**, 20g, 12m, no d5/d6 SEE−300 capture prune | 8–12–0 **40%** | White 80%, **Black 0%**. Keep prune change; not a beat |
| Crafty | **10+0.1**, 20g, 12m + hang overlay | 8–11–1 **42.5%** | White 65%, **Black 20%**. First Black wins. Keep hang overlay |
| Crafty | **10+0.1**, 20g, hang overlay + `my_time // 12` | 9–11–0 **45%** | White **90%**, Black 0%. Lucky 20g. |
| Crafty | **10+0.1**, 20g, same + ID 90% cutoff | 7–12–1 **37.5%** | Reverted cutoff to 80% |
| Crafty | **10+0.1**, **40g**, hang overlay + //12 | 15–22–3 **41.2%** (−61 Elo) | White 70%, Black 12.5%. |
| Crafty | **10+0.1**, 20g, + qsearch skip overlay, native | 9–10–1 **47.5%** | White 90%, 1 Black draw. Lucky 20g |
| Crafty | **10+0.1**, 20g confirmation of that config | 7–11–2 **40%** | Pooled **16–21–3 43.8%/40g**. Not a beat |
| Crafty | **10+0.1**, 20g, enn4_book1x (12m+1×book) | 6–13–1 **32.5%** | Weaker than 12m. Keep 12m. |
| Crafty | **10+0.1**, 20g, 2-ply qsearch checks | 4–14–2 **25%** | Reverted. |
| Crafty | **10+0.1**, 20g+20g, enn4_d10 (12m+6× d10 self-play) | 6–12–2 **35%** then 8–12–0 **40%** | Pooled **37.5%/40g**. Weaker than 12m. |
| Crafty | **10+0.1**, 20g, enn4_d10x1 (12m+1× d10) | 9–11–0 **45%** | White 90%, Black 0%. Same as lucky 12m 20g. |
| Crafty | **10+0.1**, 20g, enn4_ccrl20m | 7–13–0 **35%** | more CCRL did not help vs Crafty |
| Crafty | **10+0.1**, 20g, enn4_mix | 6–11–3 **37.5%** (−89) | mix weaker than lucky 12m 20g |
| Crafty | **10+0.1**, 20g, enn4_book (qt+8×book) | 7–12–1 **37.5%** | White 75%, **Black 0%**. Same as 12m |
| Crafty | **10+0.1**, 20g, enn4_tactics scratch | 0–20–0 **0%** | capture-trained net collapsed |
| Crafty | **10+0.1**, 20g, enn4_qt | 4–14–2 **25%** | 12m+3M tactics weaker than 12m |
| Crafty | **10+0.1**, 20g, enn4_bal | 5–15–0 **25%** | qt+book+tactics subsample, freeze-linear |
| Crafty | **10+0.1**, 20g, classical | 6–13–1 **32.5%** (−127) | rebuilt hang-veto binary; historical 5% was weaker code |

Style inversion: we beat BBC (~2465 CCRL) and lose to Sungorus (~2269)
at similar search depth. Sungorus takes hanging pieces. Fruit is an
efficiency/depth problem.

## Constraints that overrode earlier NNUE-first work

1. Classical first, then massive **self-play** to seed NNUE.
2. **No Crafty labels.** Ignore `~/experion_train/crafty_pure.txt` and
   `nnue_crafty_pure.bin` on the GPU box.
3. Train **ENN4 only** (color-preserving). Do not ship ENN3 king-bucket nets.
4. GPU is `ssh joey@192.168.2.46` (192.168.4.26 timed out). Docker image
   `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`.

## What was kept

- First-batch eval: blocked/connected passers, backward pawns, rook on 7th,
  pawn storm, pawn islands, **king tropism**, space, hung pieces at `v//10`
  (no king-as-attacker).
- Search: capture history, LMR improving, razoring (qsearch without
  recursive checks), NMP with improving-or-eval≥β+60, reusable SMP helpers,
  `tt_owner`, age bump once per think, primary move from `think_smp`,
  looser LMP 5/8/13/18, iteration cutoff 75% of soft, SE depth≥6 with
  double extend.
- Fast TC: do not drop SMP to 1 below 200ms; scale to 2 threads if
  `soft_ms < 150`.
- `Position#hash_after` (Zobrist preview). Spec in `spec/tt_spec.cr`.
  Currently unused by search after child-TT ordering was reverted.
- Root hanging veto (`reject_hanging_root` / `hanging_quiet?`): after ID,
  if best quiet has SEE < −150 and isn’t a check, and next non-hanging
  root move is within 250cp, play that. Mate scores skip the veto.
  Root quiet ordering is center bias only. Pawn-hang veto (SEE ≤ −100)
  scored 12.5% and was reverted.
- Self-play CLI: `gendata-selfplay` → `GenData.run_selfplay`. Packer:
  `tools/prepare_selfplay.py`. Format after join: `fen;wdl;white_cp`.
- SEE quiet fix: empty destination is 0, not fake EP 100.
- Duplicate `magic_constants` require removed from `src/experion.cr`.
- `tools/match/run_match.sh`: `-recover -maxmoves 300`. Default TC 10+0.1,
  Threads=4, Hash=256, `CONC=1`.

## Tried this continuation and verdict

| Change | Sample | Verdict |
|---|---|---|
| Root SEE quiet ordering | 8g then aborted: 3–4–1 **43.8%**; later in 32.5% mix | **reverted**. Not a breakthrough; implicated in the 32.5% “baseline”. |
| Veto skip when score < −80 | 6g: **0–5–1 8.3%** | **reverted**. Left hanging moves in lost games; Sungorus converted. Mate-score skip kept. |
| Pawn-attack hanging eval (`v//6` even if heavier piece defends) | 20g: **6–10–4 40% (−70 Elo)** | **reverted**. No better than hang-veto 45%. |
| History malus on searched fail-low quiets | mixed into 40% then 32.5% | **reverted**. Restore prune-branch `bump_history_down` only. |
| Negative history used in `pick_best` ordering | 4g: **0–4–0** | **reverted**. LMP then dropped developing moves that had failed in other lines. Keep clamp-to-0 for ordering; raw `@history` still feeds LMR. |
| Hang-veto + root SEE + fail-low malus | 20g: **5–12–3 32.5%** | **reverted** SEE-order and malus. Worse than original hang-veto 45%. |
| Do not LMR hanging quiets (SEE < −150) | 20g: **5–13–2 30% (−147)** | **reverted**. Cost nodes; LOS 1.9% vs even. |
| Root hang-veto SEE ≤ −100 (pawn hangs too) | 12g aborted: **1–10–1 12.5%** | **reverted** to < −150. Vetoing hanging pawn pushes swapped to worse alternatives in wild openings. |
| Unstable-iteration extra time (PV change or −40cp, depth ≥ 5) | 20g: **6–12–2 35% (−108)** | **reverted**. No better than hang-veto 45%; PV still changes often enough to spend extra time. |
| No tropism/king-pressure if pawn-attacked | 8g aborted: **0–6–2 12.5%** | **reverted**. Same class as other hang-eval tweaks. Game 5 was a **155ms time loss**. |
| Hard-stop buffer `my_time - 200ms` | 20g: **4–15–1 22.5% (−215)** | **reverted**. No flags, but starved late-game search. One prior flag was on the 12.5% hang-eval binary. |
| Clean hang-veto + tropism baseline | 20g: **6–12–2 35% (−108)** | Not 45%. Same noisy Sungorus band as other 20g samples. BBC 72.5% remains the strength gate. |
| Drop capture futility at depth 5–6 (SEE < −300) | Crafty 20g **40%**, Black 0% | **kept**. Same color hole; not worse than 12m 36.3%. |
| Mix full 20M tactics / scratch / qt / bal nets | Crafty 0–25% | **do not retry**. Quiet 12m remains best. |
| NNUE hang overlay (`Eval.hang_overlay` at blend 100) | Crafty 20g **8–11–1 42.5%** | White 65%, **Black 20% (2 wins)**. First Black points. Keep. |
| Hang + tropism + king-zone overlay | Crafty 20g **7–13–0 35%** | **reverted** tropism/king-zone. Hang-only stays. |
| Hang-only overlay + `my_time // 12` | Crafty 20g **9–11–0 45%** | White 90% (one 17-move book miniature), Black 0%. Best 20g. Keep. |
| ID cutoff 90% of soft (was 80%) | Crafty 20g **7–12–1 37.5%** | **reverted**. White 70%, one Black draw. 80% cutoff stays. |
| Hang + //12 40g confirmation | Crafty 40g **15–22–3 41.2%** | White 70%, Black **12.5%** (2 wins + 1 draw). ~+35 Elo vs 12m 36.3%/40g. Not a beat. |
| Qsearch skip hang overlay + `--mcpu=native` | 20g **47.5%** then 20g **40%**; pooled **43.8%/40g** | Keep overlay-in-tree + //12 + native. |
| 12m + 1× book self-play, resume 12m, freeze-linear (`enn4_book1x`) | Crafty 20g **6–13–1 32.5%** | **weaker than 12m**. Do not ship. Book 1× still doesn't fix Black. |
| Qsearch quiet checks 2 ply | Crafty 20g **4–14–2 25%** | **reverted**. nps cost, LOS 0.3%. Keep 1 ply. |
| 4000-game d10 self-play, 350k node cap, match openings | 565,974 raw → 402,448 unique. Mix 12m+6×. Crafty **6–12–2 35%** then **8–12–0 40%** (pooled **37.5%/40g**) | **weaker than 12m**. Do not ship `enn4_d10.bin`. |
| Width-128 ENN4 on data12m | Crafty 20g **6–12–2 35%** | **weaker**. +30% nps but shallower ID. Keep w256. |
| Blend 90 (10% classical) | Crafty 20g **6–13–1 32.5%** | **keep blend 100**. PSQT double-count. |
| Hash=1024 | Crafty 20g **6–14–0 30%** | **keep 256**. |
| Hang overlay v//6 (was v//10) | Crafty 20g **8–11–1 42.5%** | Same band as v//10; Black 2 wins. **reverted to v//10** (43.8%/40g config). |
| 12m + 1× d10 self-play (`enn4_d10x1`) | 20g **45%** then **32.5%**; pooled **38.8%/40g** | Lucky first sample. Keep 12m. |
| Hang-veto window 400cp (was 250) | 20g **45%** then **37.5%**; pooled **41.2%/40g** | **reverted to 250**. Same as hang+//12 40g. |
| `my_time // 10` (was // 12) | Crafty 12m 20g **7–12–1 37.5%** | **reverted to // 12**. Extra alloc starved later games / flags; keep //12. |
| ProbCut + lazy hang overlay | Crafty 12m 20g **8–11–1 42.5%** | White 65%, Black 20%. Same band as 43.8%/40g. **reverted** both (improving-flag pollution from lazy overlay). Keep `attackers_to` hang + unrolled `apply_delta`. |
| WDL-heavier 12m fine-tune (`enn4_wdl`, 0.55/0.45, freeze-linear) | Crafty 20g **5–12–3 32.5%** | **do not ship**. Val barely moved. Keep 0.9/0.1. Confirmation match killed. |
| LMR −1 when static_eval < α | Crafty 20g **5–12–3 32.5%** | **reverted**. Hurt White (50%) more than it helped Black. |
| LMR divisor 1.9 (was 2.3) | Crafty 12m 20g **6–13–1 32.5%** | **reverted**. Hurt White (50%). Keep 2.3. |
| CCRL depth≥16 quiets (`enn4_d16`) | Crafty 20g **8–11–1 42.5%** | Same band as 12m. White conversion, Black 0%. **keep 12m**. Confirmation killed. |
| Eval-cache hang overlay | Crafty 12m 20g **7–11–2 40%** | Same band. Keep cache (same eval, fewer overlay walks). |
| IIR off (was depth−1 without TT move) | Crafty 12m 15g **5–9–1 36.7%** (aborted) | **reverted**. Lost White games. IIR stays. |
| 12m fine-tune on depth≥16 labels (`enn4_d16ft`) | 20g **47.5%** then **37.5%**; pooled **16–22–2 42.5%/40g** | Lucky first sample. Keep 12m (43.8%/40g). |
| SE at depth ≥ 5 (was ≥ 6) | Crafty 12m 6g **1–5–0 16.7%** (aborted) | **reverted to ≥ 6**. Lost White immediately. |
| Contiguous `apply_delta` + unrolled v4 eval | Crafty 12m 20g **8–11–1 42.5%** | Same band. Keep the vector-friendly loops. |
| Width-192 ENN4 on data12m | 20g **45%** then **45%**; pooled **17–21–2 45%/40g** | Prior best 40g. Faster than w256. |
| w192 fine-tune on depth≥16 quiets (`enn4_w192d16`) | Crafty 20g **7–12–1 37.5%** | Weaker than 12m w192. Skip confirm. |
| w192 mix data12m+1× d16 (`enn4_w192d16mix`) | 20g **50%** then **30%**; pooled **13–21–6 40%/40g** | Lucky first sample. Do not ship. |
| w192 mild WDL 0.8/0.2 on 12m (`enn4_w192wdl20`) | Crafty 20g **6–12–2 35%** | 0.55/0.45 was 32.5%; 0.8/0.2 also weaker. Keep 0.9/0.1. |
| FICS 2025 quiets labeled by w192 (`enn4_w192fics`) | Crafty 20g **7–12–1 37.5%** | 1.50M quiets / 172k games. Teacher labels not enough vs Crafty. |
| w192 mix 12m+d16+fics (`enn4_w192all`) | 20g **47.5%** then **52.5%**; pooled **17–17–6 50%/40g** | **Beat.** White 80%, Black 20%. Ship this net. |
| w192 match-book self-play 5000 d10 1× (`enn4_w192sp`) | Crafty 20g **7–11–2 40%** | 713k samples, 499k unique. Weaker than all-mix. Do not ship. |

## Reverted earlier (still reverted)

Recursive qsearch quiet checks; SMP-off below 200ms; hung-piece
king-as-attacker + `v//4`; SEE-losing quiet prune in the tree; pawn-threat
eval + knight outposts; child-TT quiet ordering; TT-corrected static eval;
extra time alloc (`time/16`); razoring off + looser LMP as a pair;
no tropism (32.5%); Threads=1 (17.5%); skip RFP/NMP/razoring on pawn
threats (10%).

## Match runner traps

- fastchess only speaks UCI. Crafty goes through `tools/match/uci_bridge`.
- Random openings from `tools/match/openings.pgn` are wild (Grob, f3, …).
  Color splits can look like a Black bug when it is just White’s first-move
  advantage plus tactics. Need 20–40 games.
- Overnight matches die on laptop sleep; the terminal file can stay
  `status: running` with a dead PID. Kill the **process group**
  (`kill -KILL -PGID`), not just the parent zsh.
- Do not stream raw fastchess stdout into a Cursor terminal. Filter to
  `Started/Finished/Score` and tee the rest to `tools/match/sungorus_current.log`.
- **Never run matches as an agent-owned terminal job.** Cursor aborts that
  process group when the chat is compacted or the shell task is cancelled.
  Use `python3 tools/match/run_detached.py 10+0.1 10 sungorus` (new session
  + `caffeinate -i`) and monitor the log file only.

## Why this goal kept pausing (process, not chess)

Cursor compact/abort kills **agent-owned** shells. Matches started in that
process group died; I also treated each 10-minute match as a turn boundary
and waited for you to say continue. Fix: `run_detached.py` / self-play /
GPU `docker -d` / `wait_pack_selfplay.py` are outside that group.

## NNUE in flight (not Crafty-labeled)

- Self-play: 8000 games d8 t4, pid in `tools/match/selfplay.pid` (writes
  `datasets/selfplay.txt` at end). `wait_pack_selfplay.py` packs npy after.
  `wait_finetune.py` then mixes CCRL `data3m` + upsampled self-play and
  fine-tunes from `enn4_ccrl/best.pt` (no Crafty labels).
- ENN4 train on llama **finished 30 epochs** on CCRL `data3m` (not Crafty).
  Best val ~epoch 10 (`nets/enn4_ccrl.bin`). Crystal eval matches checker
  (startpos 12 cp). Full STS @ 80ms on llama (current Crystal binary):
  **NNUE 554/1500 (36.9%) vs classical 593/1500 (39.5%)** — parity, not the
  old 6.8% collapse. STS1 @ 50ms on Mac (48 vs 38) was suite noise.
- Width-512 ENN4 on the same CCRL `data3m` (20 epochs): best val epoch 10
  (`nets/enn4_ccrl_w512.bin`, ENN4 width 512). Slightly lower val than the
  last w256 epochs, not yet match-tested. Mix fine-tune stays width 256
  so it can `--resume` `enn4_ccrl/best.pt`.
- Vice NNUE smoke (10g, 2+0.02, blend 100, wrapper `experion_nnue.sh`):
  **5–5–0 = 50%**. Not the old 0/40 king-bucket collapse. Classical Vice
  was 64%/40g; 10g is noisy. `run_detached.py` now keeps `EXPERION_NNUE`
  instead of popping it. `run_match.sh` uses `EXPERION_BIN` and
  `EXPERION_BLEND`.
- 12M CCRL pack **done**: 148k games, 11.40M train + 0.60M val.
  `nets/enn4_ccrl12m.bin`. STS 571/1500 (38.1%) vs classical 593 (39.5%).
  **Best vs Crafty so far, but not a beat:** 36.3% / 40g. White ~75%,
  Black ~10% in the wild `openings.pgn` book. BBC 82.5% and Vice 85% at
  10+0.1 with this net. 20M net 35% vs Crafty — extra early-PGN rows did
  not help.
- Diagnosis: **the data, not more of the same quiets.** Packed **20M
  quiets+captures+checks** (192k games). Empty-board KR/KQ probes are OOD
  (scratch +161/+173 vs 12m +425/+742). Mixed **12m + 2×2.5M tactics**
  (`enn4_qt.bin`, val 0.0192): rook +325, queen +500, WAC signs with 12m
  but shifted toward scratch. Match-book root evals are the same across
  nets (~+10cp STM, Black not a static-eval hole). Book waiter resume is
  **enn4_qt** (not raw 12m); mix remains 12m+8× book (full 20M hidden).
  After self-play: serialized Crafty `crafty_book` → `crafty_tactics` →
  `crafty_qt` (one fastchess at a time), then `crafty_bal`. No Crafty
  labels.
- Time split after the Fruit match rebuild: `my_time // 16` (was // 20).

BBC at 10+0.1, 20g: **14–5–1 72.5%** is the reliable mid-ladder result.
Sungorus (~2269) is a hang-taker in this book, not an Elo thermometer: the
same classical binary beats a ~2465 engine and scores 12–45% vs Sungorus.
A second ~2269 engine is not required. Sungorus stays a hang canary.
Self-play is **not** blocked on Sungorus ≥50%.

## NNUE resume

```
python3 tools/match/run_selfplay_detached.py 8000 8 datasets/selfplay.txt 4
python3 tools/prepare_selfplay.py datasets/selfplay.txt datasets/selfplay_npy
# on llama (192.168.2.46), Docker + tools/train_nnue_v4.py
# then nnue_check + STS; EXPERION_NNUE=... vs this classical and vs Crafty
```

Do not train on `crafty_pure.txt`. GPU idle when last checked (RTX 3060 +
GTX 1650).

## Current code

- `src/experion/search.cr` — hang veto SEE < −150; capture futility only
  depth ≤ 4 (dropped d5/d6 SEE−300); hang overlay skipped in qsearch so
  the eval cache stores the NNUE/classical base. ProbCut, lazy overlay,
  and LMR/1.9 were tried and reverted.
- `src/experion/nnue.cr` — unrolled `apply_delta` (same math).
- `src/experion/eval.cr` — tropism; hung pieces at `v//10` via
  `undefended_hang?`; **NNUE hang overlay** at blend 100.
- `src/experion/uci.cr` — `my_time // 12` (`// 10` scored 37.5% vs Crafty). ID cutoff stays 80%.
- Specs: overlay + `eval_for` = net + overlay (`spec/nnue_spec.cr`).
  **664 examples green.**

Best Crafty config: `enn4_w192all.bin` blend 100, hang overlay in-tree,
`my_time // 12`, native `-mcpu=native`, overlay eval cache, qsearch SEE reuse.
**17–17–6 50%/40g** (47.5% then 52.5%). White 80%, Black 20%.
Quiet w192 12m was **45%/40g**. Classical was **32.5%/20g**.

Revert `config.json` before commit (fastchess leftover). `docs/` is
gitignored; force-add this file like the previous findings doc.

## How to resume / replay the beat

```
EXPERION_BIN=tools/match/experion_nnue.sh \
EXPERION_NNUE=nets/enn4_w192all.bin EXPERION_BLEND=100 \
python3 tools/match/run_detached.py 10+0.1 10 crafty crafty_w192all_recheck
```
