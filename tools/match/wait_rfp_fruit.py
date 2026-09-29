#!/usr/bin/env python3
"""Ship net, hang v//10, RFP only at depth<=2. 20g Fruit canary then Crafty.

Hang v//5 vs Fruit was 15% / 13g. Depth 3–4 RFP was returning static eval
in positions Fruit refutes tactically.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_rfp_fruit.log"
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


def play(log, opp: str, stem: str, rounds: str) -> None:
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
    say(log, f"{int(rounds)*2}g 10+0.1 vs {opp} net={NET.name} rfp<=2")
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
    say(log, "RFP<=2 + ship: Fruit 20g then Crafty 20g")
    play(log, "fruit", "rfp2_fruit", "10")
    play(log, "crafty", "rfp2_crafty", "10")
    say(log, "rfp2 ladder done")


if __name__ == "__main__":
    main()
