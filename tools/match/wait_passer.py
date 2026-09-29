#!/usr/bin/env python3
"""After SE canary: passed-pawn overlay on mix25, then unfrozen-linear FT.

NNUE blend 100 skips classical passers. Fruit scores them. Hang overlay
helped; a conservative EG/4 passer term is the same idea. Does not rematch
mix25 without a change. SE waiter must finish (and revert) first.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402
import wait_after_sf as was  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_passer.log"
EVAL = BASE / "src" / "experion" / "eval.cr"
SELOG = HERE / "wait_se5.log"
wsp.LOG = LOG
was.LOG = LOG

MARKER = "      # --- passed-pawn overlay (NNUE blend 100) ---"
PASSER = '''      # --- passed-pawn overlay (NNUE blend 100) ---
      wp_p = pos.pieces_of(WHITE, PAWN)
      bp_p = pos.pieces_of(BLACK, PAWN)
      pw_p = passed_pawns(wp_p, bp_p, WHITE)
      while pw_p != 0
        sq_p = pw_p.trailing_zeros_count.to_i!
        d += PASSED_EG[sq_p >> 3] // 4
        pw_p &= pw_p - 1
      end
      pb_p = passed_pawns(bp_p, wp_p, BLACK)
      while pb_p != 0
        sq_p = pb_p.trailing_zeros_count.to_i!
        d -= PASSED_EG[7 - (sq_p >> 3)] // 4
        pb_p &= pb_p - 1
      end
'''
ANCHOR = "      pos.stm == WHITE.to_u8! ? d : -d\n    end\n\n    # No way to force mate"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say
was.say = say


def se_done() -> bool:
    if not SELOG.exists():
        return True
    t = SELOG.read_text(errors="replace")
    return (
        "se5 cleared Fruit" in t
        or "se5 failed Fruit" in t
        or "llama still down" in t
        or "llama is up" in t
    )


def se_cleared() -> bool:
    return SELOG.exists() and "se5 cleared Fruit" in SELOG.read_text(errors="replace")


def rebuild() -> bool:
    say("shards build --release")
    log = open(HERE / "passer_build.out", "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    say(f"build rc={r.returncode}")
    return r.returncode == 0


def apply_passer() -> bool:
    t = EVAL.read_text()
    if MARKER in t:
        return True
    if ANCHOR not in t:
        say("hang_overlay anchor missing")
        return False
    EVAL.write_text(t.replace(ANCHOR, PASSER + ANCHOR, 1))
    say("applied passer overlay")
    return True


def revert_passer() -> None:
    t = EVAL.read_text()
    if MARKER not in t:
        return
    start = t.find(MARKER)
    end = t.find(ANCHOR, start)
    if start < 0 or end < 0:
        say("passer revert failed to find block")
        return
    EVAL.write_text(t[:start] + t[end:])
    say("reverted passer overlay")
    rebuild()


def train_uflin() -> None:
    npy = BASE / "datasets" / "ccrl_mix25_disagree_npy"
    out = BASE / "datasets" / "enn4_mix25_uflin"
    best = out / "best.bin"
    if not (npy / "train_w.npy").exists():
        say("no disagreement npy; skip uflin")
        return
    if best.exists() and wsp.nnue_ok(best):
        return
    say("train mix25 unfrozen-linear 3ep lr=1e-4 on disagreements")
    logp = HERE / "mix25_uflin_train.out"
    log = open(logp, "w", buffering=1)
    proc = subprocess.Popen(
        ["caffeinate", "-i", "python3", str(BASE / "tools" / "train_nnue_v4.py"),
         str(npy), str(out),
         "--width", "192", "--epochs", "3", "--lr", "0.0001",
         "--batch", "4096", "--device", "mps",
         "--resume", str(MIX25),
         "--eval-weight", "0.85", "--wdl-weight", "0.15"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
    )
    rc = proc.wait()
    say(f"train mix25_uflin rc={rc}")
    if rc != 0 or not best.exists() or not wsp.nnue_ok(best):
        say("uflin material bad or train failed; skip blends")
        return
    full = BASE / "nets" / "enn4_mix25_uflin.bin"
    subprocess.run(["cp", str(best), str(full)], check=True)
    for t, ttag in ((0.15, "h15"), (0.25, "h25")):
        mixed = BASE / "nets" / f"enn4_mix25_uflin_{ttag}.bin"
        subprocess.run(
            ["python3", str(BASE / "tools" / "mix_enn4.py"),
             str(MIX25), str(full), str(mixed), "--t", str(t)],
            check=True,
        )
        wsp.nnue_ok(mixed)


def main() -> None:
    say("wait_passer: uflin train during SE, then passer overlay")
    train_uflin()
    last_hb = 0.0
    while not se_done():
        now = time.time()
        if now - last_hb >= 120:
            extra = ""
            p = HERE / "mix25_se5_fruit.log"
            if p.exists():
                sc = wsp.parse_score(p.read_text(errors="replace"))
                if sc:
                    extra = f" se5 {sc[0]}-{sc[1]}-{sc[2]} = {sc[3]:.1%}/{sc[4]}g"
            say(f"waiting for SE canary{extra}")
            last_hb = now
        time.sleep(20)
    if se_cleared():
        say("SE already cleared Fruit")
        return
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if apply_passer() and rebuild():
        sc = wsp.fruit_then_crafty(MIX25, "mix25_passer", fruit_bar=0.18)
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            say("passer cleared Fruit")
            return
        if not sc or sc[3] < 0.22 or sc[4] < 18:
            say("passer failed Fruit; revert")
            revert_passer()
        else:
            say("passer held; keep overlay")
            return
    uflin = BASE / "nets" / "enn4_mix25_uflin_h25.bin"
    h15 = BASE / "nets" / "enn4_mix25_uflin_h15.bin"
    nets = [p for p in (uflin, h15) if p.exists()]
    if nets:
        say("unfrozen-linear blends vs Fruit")
        if was.match_nets(nets, "uflin"):
            say("uflin cleared Fruit")
            return
    say("passer/uflin done; cluster poll")
    last = 0.0
    while True:
        if wsp.cluster_up():
            say("llama is up")
            return
        now = time.time()
        if now - last >= 300:
            say("llama still down")
            last = now
        time.sleep(60)


if __name__ == "__main__":
    main()
