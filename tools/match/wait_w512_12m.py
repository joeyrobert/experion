#!/usr/bin/env python3
"""After the tail pack/train releases RAM and GPU 0, train width-512 on data12m."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "w512_12m.log"
HOST = "joey@192.168.2.46"
TAIL_MANIFEST = "/home/joey/experion_train/data20m_tail/manifest.json"
OUT = BASE / "nets" / "enn4_ccrl12m_w512.bin"


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
    say(log, "waiting for tail pack so RAM is free")
    while True:
        r = subprocess.run(["ssh", HOST, f"test -s {TAIL_MANIFEST}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            break
        time.sleep(20)
    say(log, "waiting for enn4_ccrl_tail/best.bin (tail train done)")
    while True:
        r = subprocess.run(["ssh", HOST, "test -s /home/joey/experion_train/enn4_ccrl_tail/best.bin"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            break
        time.sleep(15)
    docker = (
        "sudo docker rm -f experion-enn4-12m-w512 >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-12m-w512 --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data12m /w/enn4_ccrl12m_w512 "
        "--width 512 --epochs 20 --lr 0.002"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-12m-w512"])
    run(log, ["rsync", "-az",
              f"{HOST}:/home/joey/experion_train/enn4_ccrl12m_w512/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")


if __name__ == "__main__":
    main()
