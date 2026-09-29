#!/usr/bin/env python3
"""Play Crafty with enn4_qt.bin once CPU is free of other Crafty matches.

enn4_qt is 12m quiets + 2x 2.5M tactics subsample, resumed from 12m.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "qt_crafty.log"
NET = BASE / "nets" / "enn4_qt.bin"
TACTICS = BASE / "tools" / "match" / "crafty_tactics.log"
BOOK = BASE / "tools" / "match" / "crafty_book.log"
WRAPPER = BASE / "tools" / "match" / "experion_nnue.sh"


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def finished(path: Path) -> bool:
    return path.exists() and "Finished match" in path.read_text(errors="replace")


def fastchess_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "fastchess"], stdout=subprocess.DEVNULL)
    return r.returncode == 0


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for enn4_qt.bin and a free CPU (no fastchess)")
    while not (NET.exists() and NET.stat().st_size > 1000):
        time.sleep(15)
    # Prefer after the scratch-tactics sample; fall back once book has also
    # finished so we never collide with wait_book's Crafty launch.
    while True:
        if finished(TACTICS) and not fastchess_running():
            say(log, "tactics sample done; CPU free")
            break
        if finished(BOOK) and not fastchess_running():
            say(log, "book sample done; CPU free")
            break
        time.sleep(15)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(WRAPPER)
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, "launching Crafty 10+0.1 10 rounds with enn4_qt.bin")
    r = subprocess.run(
        ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
         "10+0.1", "10", "crafty", "crafty_qt"],
        cwd=str(BASE), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)
    say(log, "detached; see tools/match/crafty_qt.log")


if __name__ == "__main__":
    main()
