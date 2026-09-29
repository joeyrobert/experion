#!/usr/bin/env python3
"""Deep mix25 self-play: 350k nodes / d10, CCRL openings.

80k-node SP produced a mix25 clone (heads MAE 2, material identical). Match-time
search is deeper than those labels, so freeze-linear FT had nothing to learn.
350k-node scores should be ahead of 10+0.1 eval and worth distilling.
Does not rematch mix25. Does not retry SF / mixreg / 80k SP blends.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402
import wait_after_sf as was  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_deep_sp.log"
wsp.LOG = LOG
was.LOG = LOG

TXT = BASE / "datasets" / "selfplay_mix25_deep.txt"
OPEN = BASE / "datasets" / "ccrl_openings.fen"
NPY = BASE / "datasets" / "mix25_deep_npy"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say
was.say = say


def heads_mae(a: Path, b: Path) -> float:
    def load(path):
        raw = path.read_bytes()
        width, = struct.unpack_from("<I", raw, 4)
        count = 768 * (width + 1)
        w1 = np.frombuffer(raw, dtype="<i2", count=count, offset=8).reshape(768, width + 1)
        return w1[:, :width]
    return float(np.abs(load(a) - load(b)).mean())


def launch_deep() -> None:
    if TXT.exists() and TXT.stat().st_size > 50_000:
        say(f"reuse {TXT.name} {TXT.stat().st_size}B")
        return
    was.dump_openings()
    env = os.environ.copy()
    env["EXPERION_SELFPLAY_NNUE"] = "1"
    env["EXPERION_NNUE"] = str(MIX25)
    env["EXPERION_BLEND"] = "100"
    env["EXPERION_OPENINGS"] = str(OPEN)
    env["EXPERION_SP_NODES"] = "350000"
    say("launch selfplay 2000g d10 350k nodes from CCRL openings")
    subprocess.run(
        ["python3", str(HERE / "run_selfplay_detached.py"),
         "2000", "10", str(TXT), "4", "gendata_mix25_deep"],
        env=env, cwd=str(BASE), check=True,
    )
    got = wsp.wait_gendata(TXT, HERE / "gendata_mix25_deep.pid", timeout_s=6 * 3600)
    if got is None:
        raise SystemExit("deep selfplay failed")


def main() -> None:
    say("wait_deep_sp: 350k-node mix25 distillation")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    launch_deep()
    if not (NPY / "train_w.npy").exists():
        say(f"pack {TXT.name}")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(TXT), str(NPY)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("pack failed")
            return
    nets = was.train_blend(NPY, "mix25_deep", 8, "0.0005")
    if not nets:
        say("train failed")
    else:
        mae = heads_mae(MIX25, BASE / "nets" / "enn4_mix25_deep.bin")
        say(f"deep vs mix25 heads MAE {mae:.2f}")
        if mae < 3.0:
            say("still a clone; skip Fruit")
        elif was.match_nets(nets, "deep"):
            say("deep cleared Fruit")
            return
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
