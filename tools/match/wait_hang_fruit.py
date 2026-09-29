#!/usr/bin/env python3
"""Ship net + hang overlay v//5 vs Fruit then Crafty, 40g 10+0.1.

Tactics fine-tunes either collapsed material or scored below the 35%
Sungorus ship baseline. Fruit is still 10% with v//10; stronger undefended
hang penalty is the isolated search/eval test.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_hang_fruit.log"
NET = BASE / "nets" / "enn4_w192all.bin"


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def run(log, cmd, **kw):
    say(log, "+ " + " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)
    return r


def play(log, opp: str, stem: str, rounds: str = "20") -> None:
    while True:
        r = subprocess.run(["pgrep", "-x", "fastchess"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            break
        say(log, "waiting for fastchess")
        time.sleep(20)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, f"{int(rounds)*2}g 10+0.1 vs {opp} net={NET.name} hang=v//5")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", rounds, opp, stem], env=env, cwd=str(BASE))
    path = BASE / "tools" / "match" / f"{stem}.log"
    while True:
        if path.exists() and "Finished match" in path.read_text(errors="replace"):
            break
        time.sleep(20)
    lines = [ln for ln in path.read_text(errors="replace").splitlines()
             if "Score of Experion" in ln]
    say(log, lines[-1] if lines else f"{stem}: no score")


def main() -> None:
    log = open(LOG, "a", buffering=1)
    say(log, "hang v//5 + ship net: Fruit then Crafty")
    play(log, "fruit", "hang5_fruit", "20")
    play(log, "crafty", "hang5_crafty", "20")
    say(log, "hang5 ladder done")


if __name__ == "__main__":
    main()
