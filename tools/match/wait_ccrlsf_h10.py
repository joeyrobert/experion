#!/usr/bin/env python3
"""Weaker CCRL-SF blends (h10 then h15). h25 35%/20g failed 40g at 8%."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402

BASE = wsp.BASE
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_ccrlsf_h10.log"
wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def main() -> None:
    say("ccrlsf h10 then h15 vs Fruit")
    for name in ("enn4_mix25_ccrlsf_h10.bin", "enn4_mix25_ccrlsf_h15.bin"):
        net = BASE / "nets" / name
        if not net.exists() or not wsp.nnue_ok(net):
            say(f"skip {name}")
            continue
        sc = wsp.fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            say(f"{name} cleared Fruit")
            return
    say("h10/h15 done; cluster poll")
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
