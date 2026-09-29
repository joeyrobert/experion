#!/usr/bin/env python3
"""After wait_book finishes (or dies), mix 12m quiets + 3M tactics + book.

Resume is the 12m checkpoint. GPU stays free until enn4_book.bin exists or
the book waiter process is gone, so we cannot collide with experion-enn4-book.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "balanced.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"
BOOK_NET = BASE / "nets" / "enn4_book.bin"
BOOK_PID = BASE / "tools" / "match" / "wait_book_selfplay.pid"
NET = BASE / "nets" / "enn4_bal.bin"
WRAPPER = BASE / "tools" / "match" / "experion_nnue.sh"


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


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for enn4_book.bin")
    while not BOOK_NET.exists() or BOOK_NET.stat().st_size < 1000:
        time.sleep(20)
    say(log, "mix/train on llama; Crafty after crafty_qt")
    run(log, ["ssh", HOST, "test -s /home/joey/experion_train/data_tactics3m/manifest.json"])
    mix = (
        "sudo docker run --rm -v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/mix_nnue_npy.py /w/data12m /w/data_tactics3m /w/selfplay_book_npy "
        "/w/mixed_bal --upsample-rest 2"
    )
    run(log, ["ssh", HOST, mix])
    docker = (
        "sudo docker rm -f experion-enn4-bal >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-bal --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_bal /w/enn4_bal "
        "--epochs 15 --lr 0.0006 --resume /w/enn4_qt/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-bal"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_bal/best.bin", str(NET)])
    qt_log = BASE / "tools" / "match" / "crafty_qt.log"
    say(log, "waiting for crafty_qt to finish so Mac CPU is free")
    while True:
        if qt_log.exists() and "Finished match" in qt_log.read_text(errors="replace"):
            break
        time.sleep(15)
    while subprocess.run(["pgrep", "-f", "fastchess"], stdout=subprocess.DEVNULL).returncode == 0:
        time.sleep(10)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(WRAPPER)
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, "launching Crafty with balanced net")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "10", "crafty", "crafty_bal"], env=env)
    say(log, "Crafty bal match detached")


if __name__ == "__main__":
    main()
