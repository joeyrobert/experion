#!/usr/bin/env python3
"""Fruit the disagreement blends. Skip h10 (MAE 0.8 clone). Deep-SP was a clone.

Does not rematch mix25. h25 first — that's where the specialist actually shows.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402
import wait_after_sf as was  # noqa: E402

BASE = wsp.BASE
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_disagree_match.log"
wsp.LOG = LOG
was.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say
was.say = say


def main() -> None:
    say("disagree Fruit: h25 then h15 (skip h10 clone)")
    nets = [
        BASE / "nets" / "enn4_mix25_disagree_h25.bin",
        BASE / "nets" / "enn4_mix25_disagree_h15.bin",
    ]
    nets = [p for p in nets if p.exists()]
    if not nets:
        say("no disagreement blends")
        return
    if was.match_nets(nets, "disagree"):
        say("disagree cleared Fruit")
        return
    say("disagree done; cluster poll")
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
