#!/usr/bin/env python3
"""Singular-extension from depth 5 (was 6) on mix25. Revert if Fruit dies."""
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
LOG = HERE / "wait_se5.log"
SEARCH = BASE / "src" / "experion" / "search.cr"
wsp.LOG = LOG

NEW = "depth >= 5 && tt_depth >= depth - 3 && !in_check &&"
OLD = "depth >= 6 && tt_depth >= depth - 3 && !in_check &&"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def rebuild() -> bool:
    say("shards build --release")
    log = open(HERE / "se5_build.out", "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    say(f"build rc={r.returncode}")
    return r.returncode == 0


def revert() -> None:
    t = SEARCH.read_text()
    if NEW not in t:
        return
    SEARCH.write_text(t.replace(NEW, OLD, 1))
    say("reverted SE to depth>=6")
    rebuild()


def main() -> None:
    say("wait_se5: singular extensions from depth 5 vs Fruit")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if NEW not in SEARCH.read_text():
        say("se5 not in search.cr")
        return
    if not rebuild():
        revert()
        return
    sc = wsp.fruit_then_crafty(MIX25, "mix25_se5", fruit_bar=0.18)
    if sc and sc[3] >= 0.45 and sc[4] >= 36:
        say("se5 cleared Fruit")
        return
    if not sc or sc[3] < 0.22 or sc[4] < 18:
        say("se5 failed Fruit; revert")
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
