#!/usr/bin/env python3
"""CCRL-opening self-play from mix25. mixreg (quiet8m+SF) died 4%/12g.

Does not rematch mix25. Does not retry SF-only or mixreg blends.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402
import wait_after_sf as was  # noqa: E402

BASE = wsp.BASE
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_ccrlop.log"
wsp.LOG = LOG
was.LOG = LOG
was.wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say
was.say = say


def main() -> None:
    say("wait_ccrlop: mix25 self-play from 8k CCRL FENs")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    nets = was.run_ccrl_selfplay()
    if nets and was.match_nets(nets, "ccrlop"):
        say("ccrlop cleared Fruit")
    else:
        say("ccrlop done; cluster poll")
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
