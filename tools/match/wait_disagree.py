#!/usr/bin/env python3
"""Mine mix25's CCRL mistakes, train, then Fruit after deep-SP finishes.

Runs MPS mining/train in parallel with 350k-node self-play. Does not steal
fastchess until wait_deep_sp is done matching or skips a clone.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402
import wait_after_sf as was  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_disagree.log"
wsp.LOG = LOG
was.LOG = LOG

SRC = BASE / "datasets" / "ccrl_quiet_tac3x"
NPY = BASE / "datasets" / "ccrl_mix25_disagree_npy"
DEEP_LOG = HERE / "wait_deep_sp.log"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say
was.say = say


def deep_queue_done() -> bool:
    if not DEEP_LOG.exists():
        return False
    text = DEEP_LOG.read_text(errors="replace")
    return (
        "still a clone" in text
        or "deep cleared Fruit" in text
        or "llama still down" in text
        or "llama is up" in text
    )


def deep_cleared() -> bool:
    return DEEP_LOG.exists() and "deep cleared Fruit" in DEEP_LOG.read_text(errors="replace")


def mine() -> Path | None:
    if (NPY / "train_w.npy").exists():
        return NPY
    if not (SRC / "train_w.npy").exists():
        say(f"missing {SRC}")
        return None
    say("mine mix25 disagreements on quiet_tac3x (|err|>=180, |cp|<=800)")
    logp = HERE / "mine_disagree.out"
    log = open(logp, "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "python3", str(BASE / "tools" / "mine_disagreement.py"),
         str(SRC), str(NPY),
         "--resume", str(MIX25),
         "--min-err", "180", "--max-abs", "800", "--cap", "800000",
         "--device", "mps"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    if r.returncode != 0 or not (NPY / "train_w.npy").exists():
        say("mine failed")
        if logp.exists():
            say(logp.read_text(errors="replace")[-600:])
        return None
    return NPY


def main() -> None:
    say("wait_disagree: hard-example CCRL FT while deep SP runs")
    npy = mine()
    nets = was.train_blend(npy, "mix25_disagree", 8, "0.0004") if npy else []
    last_hb = 0.0
    while not deep_queue_done():
        now = time.time()
        if now - last_hb >= 120:
            extra = ""
            gen = HERE / "gendata_mix25_deep.log"
            if gen.exists():
                lines = [ln for ln in gen.read_text(errors="replace").splitlines()
                         if ln.startswith("selfplay w")]
                extra = f" {lines[-1]}" if lines else ""
            say(f"waiting for deep-SP queue{extra}")
            last_hb = now
        time.sleep(20)
    if deep_cleared():
        say("deep SP already cleared Fruit; cluster poll")
    elif not nets:
        say("no disagreement net")
    else:
        while wsp.fastchess_up():
            say("waiting for fastchess")
            time.sleep(15)
        if was.match_nets(nets, "disagree"):
            say("disagree cleared Fruit")
            return
        say("disagree did not clear")
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
