#!/usr/bin/env python3
"""Wait for the 12M CCRL pack, train ENN4 from scratch, copy best.bin home.

Does not use crafty_pure. Waits if another experion GPU train is running.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "ccrl12m.log"
HOST = "joey@192.168.2.46"
REMOTE_MANIFEST = "/home/joey/experion_train/data12m/manifest.json"
OUT_NET = BASE / "nets" / "enn4_ccrl12m.bin"


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def run(log, cmd):
    say(log, "+ " + " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for data12m/manifest.json")
    while True:
        r = subprocess.run(
            ["ssh", HOST, f"test -s {REMOTE_MANIFEST}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            break
        time.sleep(20)
    say(log, "pack ready; waiting for other GPU trains")
    run(log, ["ssh", HOST,
              "sudo docker wait experion-enn4-mix >/dev/null 2>&1 || true; "
              "sudo docker wait experion-enn4-w512 >/dev/null 2>&1 || true"])
    docker = (
        "sudo docker rm -f experion-enn4-12m >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-12m --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data12m /w/enn4_ccrl12m --epochs 25 --lr 0.002"
    )
    run(log, ["ssh", HOST, docker])
    say(log, "training; waiting")
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-12m"])
    run(log, ["rsync", "-az", f"{HOST}:/home/joey/experion_train/enn4_ccrl12m/best.bin",
              str(OUT_NET)])
    say(log, f"wrote {OUT_NET}")


if __name__ == "__main__":
    main()
