#!/usr/bin/env python3
"""Pack CCRL with captures/checks and train ENN4. No Crafty labels.

Train into enn4_tactics_run and only publish enn4_tactics/best.pt after the
container exits, so the book waiter cannot resume a mid-epoch checkpoint
or steal GPU 0.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "tactics.log"
HOST = "joey@192.168.2.46"
MANIFEST = "/home/joey/experion_train/data_tactics/manifest.json"
PUBLISH = "/home/joey/experion_train/enn4_tactics/best.pt"
OUT = BASE / "nets" / "enn4_tactics.bin"


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
    say(log, "waiting for tactics pack")
    while True:
        r = subprocess.run(["ssh", HOST, f"test -s {MANIFEST}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            break
        time.sleep(20)
    docker = (
        "sudo docker rm -f experion-enn4-tactics >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-tactics --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data_tactics /w/enn4_tactics_run --epochs 25 --lr 0.002"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-tactics"])
    publish = (
        "mkdir -p /home/joey/experion_train/enn4_tactics && "
        "cp -a /home/joey/experion_train/enn4_tactics_run/best.pt "
        "/home/joey/experion_train/enn4_tactics/best.pt && "
        "cp -a /home/joey/experion_train/enn4_tactics_run/best.bin "
        "/home/joey/experion_train/enn4_tactics/best.bin"
    )
    run(log, ["ssh", HOST, publish])
    run(log, ["rsync", "-az", f"{HOST}:{PUBLISH.rsplit('/', 1)[0]}/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")


if __name__ == "__main__":
    main()
