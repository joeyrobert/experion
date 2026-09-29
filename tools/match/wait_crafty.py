#!/usr/bin/env python3
"""After enn4_book.bin's first Crafty sample, run a second 20-round match.

wait_book_selfplay launches crafty_book (20 games if the in-memory waiter
still has rounds=10, 40 if restarted from disk). This waiter waits for that
log to finish, then plays another 20 rounds (40 games) so a beat is not a
single noisy 20g sample. Does not rebuild while gendata-selfplay is alive.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
NET = BASE / "nets" / "enn4_book.bin"
FIRST = BASE / "tools" / "match" / "crafty_book.log"
LOG = BASE / "tools" / "match" / "wait_crafty.log"
WRAPPER = BASE / "tools" / "match" / "experion_nnue.sh"
GENDATA = "gendata-selfplay"


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def running(name: str) -> bool:
    r = subprocess.run(["pgrep", "-f", name], stdout=subprocess.DEVNULL)
    return r.returncode == 0


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for enn4_book.bin")
    while not NET.exists() or NET.stat().st_size < 1000:
        time.sleep(20)
    say(log, "waiting for first Crafty sample to finish")
    while True:
        if FIRST.exists() and "Finished match" in FIRST.read_text(errors="replace"):
            break
        time.sleep(15)
    say(log, FIRST.read_text(errors="replace")[-400:])
    while running(GENDATA):
        say(log, "gendata still running; not rebuilding")
        time.sleep(30)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(WRAPPER)
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, "launching Crafty 10+0.1 20 rounds (40 games) crafty_book_b")
    r = subprocess.run(
        ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
         "10+0.1", "20", "crafty", "crafty_book_b"],
        cwd=str(BASE),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)
    say(log, "second Crafty match detached; see tools/match/crafty_book_b.log")


if __name__ == "__main__":
    main()
