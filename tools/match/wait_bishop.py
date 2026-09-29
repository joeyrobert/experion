#!/usr/bin/env python3
"""Bishop-pair overlay on mix25 hang_overlay. Revert if Fruit dies.

NNUE blend 100 skips classical pair. +25cp both-bishops. Does not rematch
mix25 without this change. Passer overlay was 17.5%.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_bishop.log"
EVAL = BASE / "src" / "experion" / "eval.cr"
wsp.LOG = LOG

NEW = "      d += 25 if pos.pieces_of(WHITE, BISHOP).popcount >= 2\n      d -= 25 if pos.pieces_of(BLACK, BISHOP).popcount >= 2\n"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def rebuild() -> bool:
    say("shards build --release")
    log = open(HERE / "bishop_build.out", "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    say(f"build rc={r.returncode}")
    return r.returncode == 0


def revert() -> None:
    t = EVAL.read_text()
    if NEW not in t:
        return
    EVAL.write_text(t.replace(NEW, "", 1))
    say("reverted bishop-pair overlay")
    rebuild()


def main() -> None:
    say("wait_bishop: +25 pair overlay vs Fruit on mix25")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if NEW not in EVAL.read_text():
        say("bishop overlay not in eval.cr")
        return
    if not rebuild():
        revert()
        return
    sc = wsp.fruit_then_crafty(MIX25, "mix25_bishop", fruit_bar=0.18)
    if sc and sc[3] >= 0.45 and sc[4] >= 36:
        say("bishop cleared Fruit")
        return
    if not sc or sc[3] < 0.22 or sc[4] < 18:
        say("bishop failed Fruit; revert")
        revert()
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
