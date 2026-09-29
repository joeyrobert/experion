#!/usr/bin/env python3
"""ProbCut canary on mix25. Revert search.cr if Fruit <18%/12g."""
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
LOG = HERE / "wait_probcut.log"
wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def main() -> None:
    say("ProbCut canary on mix25")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    say("rebuild with ProbCut")
    r = subprocess.run(["caffeinate", "-i", "shards", "build", "--release"], cwd=str(BASE))
    say(f"shards build rc={r.returncode}")
    if r.returncode != 0:
        return
    spec = subprocess.run(["crystal", "spec"], cwd=str(BASE), capture_output=True, text=True)
    tail = (spec.stdout or "").strip().splitlines()[-5:]
    say(f"spec rc={spec.returncode} {tail}")
    if spec.returncode != 0:
        say("spec failed — revert ProbCut")
        subprocess.run(["git", "checkout", "--", "src/experion/search.cr"], cwd=str(BASE))
        subprocess.run(["caffeinate", "-i", "shards", "build", "--release"], cwd=str(BASE))
        return
    sc = wsp.play(MIX25, "fruit", "mix25_probcut_fruit", "10",
                  abort_after=12, abort_below=0.12)
    if not sc or sc[3] < 0.18:
        say("ProbCut failed Fruit — revert")
        subprocess.run(["git", "checkout", "--", "src/experion/search.cr"], cwd=str(BASE))
        subprocess.run(["caffeinate", "-i", "shards", "build", "--release"], cwd=str(BASE))
        say("reverted ProbCut and rebuilt ship search")
    else:
        say("ProbCut held Fruit — Crafty next")
        wsp.play(MIX25, "crafty", "mix25_probcut_crafty", "10",
                 abort_after=14, abort_below=0.18)
        if sc[3] >= 0.26:
            wsp.play(MIX25, "fruit", "mix25_probcut_fruit40", "20",
                     abort_after=18, abort_below=0.15)
    say("probcut waiter done; cluster poll")
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
