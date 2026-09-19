# Training handoff (2026-09-18)

Paused at Joey’s request. **Goal is not met.** Pass this file to the next agent; do not rematch mix25 hoping 21% lucks into 50%.

## Goal

Make Experion clearly stronger than **Fruit 2.1** and **local Crafty 25.2**: **≥50% over 40 games** at **10+0.1**, shippable net.

- Judge by match results, not WAC/STS (±5 noise).
- Crystal engine only. No Crafty-labeled training. No 5TB Lichess dump.
- Training cluster **llama** (`joey@192.168.2.46`) was **down** (SSH refused) for this whole local stretch.

## Current best (authoritative)

| Opponent | Protocol | Result | Notes |
|---|---|---|---|
| Fruit 2.1 (CCRL 2694) | 10+0.1, Threads=4, Hash=256, CONC=1, `openings.pgn` | **mix25 21%/40g** | Best **confirmed** Fruit. 20g ≥26% is **not** a ship; need 40g confirm (abort 18g/0.15). |
| Crafty 25.2 local | same TC, **fair STM clocks** via `uci_bridge` | **~5–18%/20g** | **Not** the old 45%. That 45% was a bridge bug: Crafty always got White’s clock. |
| Crafty misclocked | old bridge | 45% (W 82.5% / B 7.5%) | Do not treat as Elo. |

**Ship / match net:** `nets/enn4_tactics_mix25.bin`  
ENN4 768→H=192 clipped ReLU + linear PSQT. Mix25 = **25% frozen-tactics heads** interpolated onto **ship linear** (`enn4_w192all.bin`). Material rook/queen ~**299/526**.

Default wrapper `tools/match/experion_nnue.sh` still points at `enn4_w192all.bin`. Matches must set:

```
EXPERION_NNUE=/Users/joey/Repos/experion/nets/enn4_tactics_mix25.bin
EXPERION_BLEND=100
```

Elo gap: Vice-anchored local ~2240. Fruit CCRL 2694 ⇒ ~450 Elo above Experion. mix25’s 21% vs Fruit is still ~200 Elo short of a 50% score.

## Engine state in this commit (kept)

All failed search/eval canaries were **reverted**. Binary should be rebuilt `--release` after pull.

| Knob | Value | Why |
|---|---|---|
| LMP | **8/12/18/24** (+2 if improving) | Only search keep vs Fruit (22.5%/20g, mix25 noise-or-slightly-better). Original was 5/8/13/18. |
| LMR | `/2.3` | Kept from earlier; 3.0 and 2.1 failed. |
| NMP | `r = 2 + depth//5` (+1 if depth>7) plus `min((eval-b)//200, 3)` | Eval-scale kept. |
| SEE prune | `-(80*depth)` | 50 failed. |
| IIR | on | Off failed. |
| Razoring | depth ≤2 | Off failed. |
| Hang-veto | root SEE < −150, window 250cp | No-veto worse. |
| Hang overlay | `v//10` at blend 100 | `v//5` failed Fruit. |
| Time | `alloc = my_time//12 + inc*3//4`; `hard_ms = min(alloc*5, my_time*3//4, 2200)` | 2× hard_ms failed. |
| gendata-selfplay | ply cap **160**, adjudicate `\|score_white\|≥1500` after ply≥16 | Stops 400k-node endgame stalls. |
| uci_bridge | **STM** wtime/btime | Required for honest Crafty. Rebuild `uci_bridge` if missing. |

Match defaults used here: **CONC=1, Threads=4, Hash=256** (CLAUDE.md still mentions 7 threads; ignore that for these bosses).

## Do not retry (local evidence)

Local freeze-linear FT of mix25 on small/foreign sets either **cloned mix25** (heads MAE ≲4, Fruit ~21%) or **died** (typically abort 4–12% at 12g). 20g ≥26% **must** 40g-confirm; several “new bests” collapsed:

- qtac_h25 25%/20g → 12.5%/24g
- x1 30%/20g → 8% at 18g
- ccrlsf_h25 35%/20g → 8.3%/18g

**Failed FT (do not rerun):** scratch tactics; 40M unfrozen tactics; quiet-only FT; extra CCRL windows skip6e9 / skip15e8 as 25% blends; FICS eval-teacher; FICS WDL-heavy; Fruit-PGN WDL; SF on self-play; SF on 74k fruit-match FENs; SF-CCRL 150k; **SF-CCRL 750k** h10 = 20%/20g (noise); quiet8m+SF mixreg 4%/12g; disagreement mining 800k (err≥180) h25 11.5% / h15 8.3%; unfrozen-linear 3ep lr=1e-4 on disagreements (clone, 299/526); 80k-node self-play (clone MAE 2); 350k-node d10 self-play (MAE 4.01, skipped as clone); more mix25 self-play in general.

**Failed search/eval canaries (reverted):** hang v//5; RFP≤2; NMP verify; mix40/mix15; no-veto; QS 2-ply; check extension; QS delta 400; 2× hard_ms; LMR 3.0/2.1; NMP no-eval-scale; SEE 50; IIR-off; NMP r−1; razoring off; ProbCut (Fruit 22.5% noise then Crafty 0/14); LMP 12/18/24/32 (17.5%/20g); history gravity (8.3%/12g); quiet futility depth≤1 (8.3%/12g); SE from depth 5 (8.3%/12g); passer overlay EG/4 (17.5%/20g); bishop-pair +25 (11.5%/13g); Threads=1 vs Fruit.

Soft 3ep lr=1e-4 is a **no-op**. Hard FT that actually moves is freeze-linear **8ep lr=1e-3** (or 5e-4 on larger sets).

## Why local FT stalled

1. **Wrong teacher:** Stockfish d8 cp is a different scale/style than mix25. Distilling it onto mix25 heads overfits a lucky 20g then dies at 40g.
2. **Self-play is tautological:** mix25 labeling mix25 games at ≤350k nodes is **shallower than 10+0.1 search**, so freeze-linear has nothing new to learn (heads MAE 2–4).
3. **Search is already full:** SE, IIR, LMR, LMP, NMP, razoring, RFP, capture/continuation history, hang-veto. Remaining knobs are ~10–50 Elo; we need ~200.
4. **Closing the gap needs cluster-scale data** (or a net that actually moves on a teacher in mix25’s units).

## On disk (not all in git)

`datasets/` is gitignored. Still on the machine:

| Path | What |
|---|---|
| `datasets/scored_mix25_d8.txt.part{0-3}` | **88k** mix25 d8 random-walk samples. Gen was killed mid-run (2500 walks planned). Concat parts → pack → freeze-linear was the in-flight experiment. |
| `datasets/ccrl_sf19_750k.txt` + `_npy` | 750k SF d8 labels (150k + 600k skip 4e9). Already trained; Fruit 20%. |
| `datasets/ccrl_quiet8m/` | 8M CCRL d16 quiets npy. |
| `datasets/ccrl_quiet_tac3x/` | 15M quiet+tactics upsample. |
| `datasets/ccrl_mix25_disagree_npy` | 800k hard examples (`\|mix25−CCRL\|≥180`, `\|cp\|≤800`). FT died. |
| `datasets/ccrl_openings.fen` | 8k CCRL FENs for self-play openings. |
| `nets/enn4_mix25_*.bin` | Failed specialists/blends. Do not ship. mix25 itself is in git. |

Stockfish 19: `/opt/homebrew/bin/stockfish`. Labeler: `tools/label_uci.py` (UCI STM cp → white_cp).

## Tools worth using

```
shards build --release
# Fruit / Crafty (honest):
CONC=1 THREADS=4 HASH=256 EXPERION_NNUE=nets/enn4_tactics_mix25.bin EXPERION_BLEND=100 \
  zsh tools/match/run_match.sh 10+0.1 20 fruit   # 40g = rounds 20
# XBoard Crafty goes through tools/match/uci_bridge (STM clocks). Rebuild:
crystal build --release -o tools/match/uci_bridge tools/match/uci_bridge.cr

python3 tools/train_nnue_v4.py <npy> <out> --width 192 --epochs 8 --lr 0.0005 \
  --batch 4096 --device mps --resume nets/enn4_tactics_mix25.bin --freeze-linear \
  --eval-weight 0.85 --wdl-weight 0.15
# MPS: no embedding_bag; no non_blocking copies (NaNs). load_enn4 resumes from .bin.

python3 tools/mix_enn4.py mix25.bin specialist.bin out.bin --t 0.25
# Keeps A's linear column; interpolates heads/bias/output.

python3 tools/match/run_waiter_detached.py script.py stem   # start_new_session + caffeinate
```

Material sanity (`tools/nnue_check.py`): rook **200–700**, queen **400–1000**.

**Laptop lid sleep stalls gen** even with caffeinate. Leave Mac awake and plugged in.

Do **not** rebuild `bin/experion` while `gendata-selfplay` uses it. Do **not** start fastchess during gendata or SF labeling (CPU fight). `pkill fastchess` without a waiter abort watcher hangs `wait_log` for 3600s.

## Suggested next (for the other agent)

Highest EV is **not** another 8-epoch freeze-linear on a small local set.

1. **Bring llama up** and train at the scale mix25 came from (tactics heads + ship linear, millions of positions), then 40g Fruit **before** claiming a new best.
2. If staying local: finish/concat `scored_mix25_d8.txt.part*` (88k), pack, freeze-linear, **t=0.10 first**, abort Fruit 12g/0.12. Random-walk labels may be junk; regularize with quiet8m if the specialist MAE is large and Fruit dies.
3. Do **not** treat 20g ≥26% as ship. Do **not** rematch mix25. Do **not** revive ProbCut, SF-as-teacher, or mix25 self-play at ≤350k nodes.

## Peers already acquired (local ladder)

Teki ~2400, Cinnamon 2336, WyldChess 2679, plus Sungorus/BBC/Vice/Glaurung in `tools/match/run_match.sh`. Bosses remain Fruit and fair Crafty.
