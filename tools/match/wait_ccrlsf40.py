#!/usr/bin/env python3
"""40g Fruit confirm of mix25_ccrlsf_h25 (20g was 35%). Then Crafty if it holds."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402

BASE = wsp.BASE
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_ccrlsf40.log"
NET = BASE / "nets" / "enn4_mix25_ccrlsf_h25.bin"
wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def main() -> None:
    say("40g Fruit confirm mix25_ccrlsf_h25 (20g was 6-12-2 = 35%)")
    logp = HERE / "mix25_ccrlsf_h25_fruit40.log"
    t0 = time.time()
    while not logp.exists() and time.time() - t0 < 90:
        time.sleep(2)
    sc = wsp.wait_log(logp, abort_after=18, abort_below=0.15, timeout_s=3600)
    if not sc:
        say("no fruit40 score")
        return
    say(f"fruit40 {sc[0]}-{sc[1]}-{sc[2]} = {sc[3]:.1%} / {sc[4]}g")
    if sc[3] >= 0.45 and sc[4] >= 36:
        say("HELD Fruit 40g — Crafty 40g")
        wsp.play(NET, "crafty", "mix25_ccrlsf_h25_crafty40", "20",
                 abort_after=16, abort_below=0.18)
    elif sc[3] >= 0.26 and sc[4] >= 18:
        say("still interesting; Crafty 20g")
        wsp.play(NET, "crafty", "mix25_ccrlsf_h25_crafty", "10",
                 abort_after=14, abort_below=0.18)
    else:
        say("40g failed confirm — mix25 remains Fruit net")
    last = 0.0
    say("cluster poll")
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
