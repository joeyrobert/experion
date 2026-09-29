#!/usr/bin/env python3
"""Quiet futility depth<=1 canary on mix25 (was <=2). Revert if Fruit dies.

LMP less-pruning held; gravity and LMP2 did not. Does not rematch mix25
without this change.
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
LOG = HERE / "wait_fut1.log"
SEARCH = BASE / "src" / "experion" / "search.cr"
wsp.LOG = LOG

NEW = "prune_futility = true if depth <= 1 &&"
OLD = "prune_futility = true if depth <= 2 &&"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def rebuild() -> bool:
    say("shards build --release")
    log = open(HERE / "fut1_build.out", "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    say(f"build rc={r.returncode}")
    return r.returncode == 0


def revert() -> None:
    t = SEARCH.read_text()
    if NEW not in t:
        say("fut1 marker missing")
        return
    SEARCH.write_text(t.replace(NEW, OLD, 1))
    say("reverted quiet futility to depth<=2")
    rebuild()


def main() -> None:
    say("wait_fut1: quiet futility depth<=1 vs Fruit on mix25")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if NEW not in SEARCH.read_text():
        say("fut1 not in search.cr")
        return
    if not rebuild():
        say("build failed")
        revert()
        return
    sc = wsp.fruit_then_crafty(MIX25, "mix25_fut1", fruit_bar=0.18)
    if sc and sc[3] >= 0.45 and sc[4] >= 36:
        say("fut1 cleared Fruit")
        return
    if not sc or sc[3] < 0.22 or sc[4] < 18:
        say("fut1 failed Fruit; revert")
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
