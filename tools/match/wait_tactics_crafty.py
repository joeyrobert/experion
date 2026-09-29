#!/usr/bin/env python3
"""When book self-play is packed, play Crafty with the from-scratch tactics net.

Runs after local selfplay_book_npy exists so packing is done and Mac CPU is
free while llama mixes/trains enn4_book. Does not rebuild bin/experion.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "tactics_crafty.log"
NPY = BASE / "datasets" / "selfplay_book_npy" / "manifest.json"
NET = BASE / "nets" / "enn4_tactics.bin"
WRAPPER = BASE / "tools" / "match" / "experion_nnue.sh"


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for selfplay_book_npy (pack done, CPU free)")
    while not NPY.exists():
        time.sleep(15)
    if not NET.exists():
        say(log, f"missing {NET}")
        sys.exit(1)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(WRAPPER)
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, "launching Crafty 10+0.1 10 rounds with enn4_tactics.bin")
    r = subprocess.run(
        ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
         "10+0.1", "10", "crafty", "crafty_tactics"],
        cwd=str(BASE), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)
    say(log, "detached; see tools/match/crafty_tactics.log")


if __name__ == "__main__":
    main()
