#!/usr/bin/env python3
"""LMP 12/18/24/32 canary on mix25. 8/12/18/24 was the only search keep vs Fruit.

If Fruit dies, revert to 8/12/18/24 and rebuild so the ship binary stays on
the known-good margins. Does not rematch mix25 without a change.
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
LOG = HERE / "wait_lmp2.log"
SEARCH = BASE / "src" / "experion" / "search.cr"
wsp.LOG = LOG

LMP2 = """          lmp_margin = if depth == 1
                        12
                      elsif depth == 2
                        18
                      elsif depth == 3
                        24
                      else
                        32
                      end"""

LMP1 = """          lmp_margin = if depth == 1
                        8
                      elsif depth == 2
                        12
                      elsif depth == 3
                        18
                      else
                        24
                      end"""


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def rebuild() -> bool:
    say("shards build --release")
    log = open(HERE / "lmp2_build.out", "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    say(f"build rc={r.returncode}")
    return r.returncode == 0


def revert_lmp1() -> None:
    text = SEARCH.read_text()
    if LMP2 not in text:
        say("LMP2 block missing; skip revert")
        return
    SEARCH.write_text(text.replace(LMP2, LMP1, 1))
    say("reverted LMP to 8/12/18/24")
    rebuild()


def main() -> None:
    say("wait_lmp2: LMP 12/18/24/32 vs Fruit on mix25")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if LMP2 not in SEARCH.read_text():
        say("LMP2 not in search.cr")
        return
    if not rebuild():
        say("build failed")
        revert_lmp1()
        return
    sc = wsp.fruit_then_crafty(MIX25, "mix25_lmp2", fruit_bar=0.18)
    if sc and sc[3] >= 0.45 and sc[4] >= 36:
        say("LMP2 cleared Fruit")
        return
    if not sc or sc[3] < 0.22 or sc[4] < 18:
        say("LMP2 failed Fruit; revert")
        revert_lmp1()
    else:
        say(f"LMP2 held {sc[3]:.1%} / {sc[4]}g — keep margins, 40g should already have run")
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
