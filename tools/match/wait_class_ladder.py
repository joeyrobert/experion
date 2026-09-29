#!/usr/bin/env python3
"""Sequential 20g 10+0.1 matches with the shipped w192all net.

Opponents sit in Crafty's CCRL neighborhood plus the engines that
already bound the local scale. One fastchess at a time.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_class_ladder.log"
MATCHES = [
    ("fruit", "class_fruit"),
    ("gnuchess", "class_gnuchess"),
    ("glaurung", "class_glaurung"),
    ("vice", "class_vice"),
    ("bbc", "class_bbc"),
]


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


def wait_fastchess(log) -> None:
    while True:
        r = subprocess.run(["pgrep", "-x", "fastchess"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return
        say(log, "waiting for fastchess")
        time.sleep(20)


def play(log, opp: str, stem: str) -> None:
    wait_fastchess(log)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(BASE / "nets" / "enn4_w192all.bin")
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, f"20g 10+0.1 vs {opp}")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "10", opp, stem], env=env, cwd=str(BASE))
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
    say(log, "Crafty-class ladder, enn4_w192all blend 100")
    for opp, stem in MATCHES:
        done = BASE / "tools" / "match" / f"{stem}.log"
        if done.exists() and "Finished match" in done.read_text(errors="replace"):
            say(log, f"skip {stem}, already finished")
            continue
        play(log, opp, stem)
    say(log, "class ladder done")
    run(log, ["python3", str(BASE / "tools" / "match" / "elo.py")])


if __name__ == "__main__":
    main()
