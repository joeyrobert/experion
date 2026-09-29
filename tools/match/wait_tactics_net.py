#!/usr/bin/env python3
"""Pack CCRL tactics labels, train ENN4 on local MPS, then 40g Fruit+Crafty.

The ship net was quiet-trained. Fruit and Sungorus punish hanging pieces;
CCRL comments at depth>=10 including captures/checks are the missing signal.
llama (192.168.2.46) is down, so this uses the Mac GPU.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_tactics_net.log"
PGN_DIR = BASE / "datasets" / "ccrl4040"
PACK = BASE / "datasets" / "ccrl_tactics40m"
NET = BASE / "nets" / "enn4_tactics40m_frozen.bin"
TRAIN_OUT = BASE / "datasets" / "enn4_tactics40m_frozen"


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


def find_pgn() -> Path:
    hits = list(PGN_DIR.rglob("*.pgn"))
    if not hits:
        raise FileNotFoundError(f"no pgn under {PGN_DIR}")
    hits.sort(key=lambda p: p.stat().st_size, reverse=True)
    return hits[0]


def extract_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "7z x .*ccrl4040"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def wait_extract(log) -> Path:
    while extract_running():
        say(log, "waiting for 7z to finish")
        time.sleep(20)
    p = find_pgn()
    say(log, f"pgn ready {p} {p.stat().st_size}")
    return p


def wait_fastchess(log) -> None:
    while True:
        r = subprocess.run(["pgrep", "-x", "fastchess"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return
        say(log, "waiting for fastchess")
        time.sleep(20)


def play(log, opp: str, stem: str, rounds: str = "20") -> None:
    wait_fastchess(log)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, f"{int(rounds)*2}g 10+0.1 vs {opp}")
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
    say(log, "tactics net: pack ~40M CCRL quiets+captures (~200k/neuron at w192)")
    pgn = wait_extract(log)
    if not (PACK / "train_w.npy").exists():
        PACK.mkdir(parents=True, exist_ok=True)
        run(log, ["python3", str(BASE / "tools" / "prepare_ccrl.py"),
                  str(pgn), str(PACK),
                  "--positions", "40000000", "--min-depth", "10",
                  "--include-tactics"], cwd=str(BASE))
    else:
        say(log, "pack already exists")
    TRAIN_OUT.mkdir(parents=True, exist_ok=True)
    if not (TRAIN_OUT / "best.bin").exists():
        # Fine-tune the ship net on MPS. From-scratch tactics already
        # collapsed material; llama is unreachable so this stays local.
        ship = BASE / "nets" / "enn4_w192all.bin"
        cmd = ["python3", str(BASE / "tools" / "train_nnue_v4.py"),
               str(PACK), str(TRAIN_OUT),
               "--epochs", "6", "--lr", "0.0003", "--width", "192",
               "--batch", "4096", "--device", "mps",
               "--eval-weight", "0.9", "--wdl-weight", "0.1",
               "--freeze-linear"]
        if ship.exists():
            cmd += ["--resume", str(ship)]
        run(log, cmd, cwd=str(BASE))
    run(log, ["cp", str(TRAIN_OUT / "best.bin"), str(NET)])
    say(log, f"wrote {NET}")
    play(log, "sungorus", "tacnet_sungorus", "20")
    play(log, "fruit", "tacnet_fruit", "20")
    play(log, "crafty", "tacnet_crafty", "20")
    say(log, "tactics-net ladder done")


if __name__ == "__main__":
    main()
