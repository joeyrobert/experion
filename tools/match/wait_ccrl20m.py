#!/usr/bin/env python3
"""Wait for data20m pack, train ENN4, copy best.bin. No Crafty labels."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "ccrl20m.log"
HOST = "joey@192.168.2.46"
MANIFEST = "/home/joey/experion_train/data20m/manifest.json"
OUT = BASE / "nets" / "enn4_ccrl20m.bin"


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
    say(log, "waiting for data20m")
    while True:
        r = subprocess.run(["ssh", HOST, f"test -s {MANIFEST}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            break
        time.sleep(20)
    say(log, "pack ready; train")
    docker = (
        "sudo docker rm -f experion-enn4-20m >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-20m --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data20m /w/enn4_ccrl20m --epochs 25 --lr 0.002"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-20m"])
    run(log, ["rsync", "-az",
              f"{HOST}:/home/joey/experion_train/enn4_ccrl20m/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")


if __name__ == "__main__":
    main()
