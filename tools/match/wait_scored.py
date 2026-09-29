#!/usr/bin/env python3
"""Scored random-walk distillation: mix25 d8 labels on diverse walks.

Self-play games clone mix25 (same distribution). Random walks hit weird
tactics mix25's eval never sees. Freeze-linear + 15/25% blend. Does not
rematch mix25.
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
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_scored.log"
TXT = BASE / "datasets" / "scored_mix25_d8.txt"
NPY = BASE / "datasets" / "scored_mix25_d8_npy"
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
    say("wait_scored: mix25 d8 random-walk labels")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if not (TXT.exists() and TXT.stat().st_size > 50_000):
        env = os.environ.copy()
        env["EXPERION_NNUE"] = str(MIX25)
        env["EXPERION_BLEND"] = "100"
        logp = HERE / "gendata_scored_d8.log"
        pidp = HERE / "gendata_scored_d8.pid"
        log = open(logp, "w", buffering=1)
        say("launch gendata-scored 2500 walks d8 t4")
        proc = subprocess.Popen(
            ["caffeinate", "-i", str(BASE / "bin" / "experion"),
             "gendata-scored", "2500", "8", str(TXT), "4"],
            cwd=str(BASE), env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )
        pidp.write_text(str(proc.pid) + "\n")
        rc = proc.wait()
        say(f"gendata-scored rc={rc} size={TXT.stat().st_size if TXT.exists() else 0}")
        if rc != 0 or not TXT.exists() or TXT.stat().st_size < 50_000:
            say("scored gen failed")
            return
    if not (NPY / "train_w.npy").exists():
        say("pack scored")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(TXT), str(NPY)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("pack failed")
            return
    nets = was.train_blend(NPY, "mix25_scored", 6, "0.0003")
    if nets and was.match_nets(nets, "scored"):
        say("scored cleared Fruit")
        return
    say("scored done; cluster poll")
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
