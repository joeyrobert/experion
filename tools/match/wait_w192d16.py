#!/usr/bin/env python3
"""Fine-tune w192 on existing depth>=16 CCRL quiets. Copy net only; do not match
while local gendata-selfplay owns the CPU.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_w192d16.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"
OUT = BASE / "nets" / "enn4_w192d16.bin"


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


def main() -> None:
    log = open(LOG, "w", buffering=1)
    run(log, ["rsync", "-az", str(BASE / "tools" / "train_nnue_v4.py"),
              f"{HOST}:{REMOTE}/train_nnue_v4.py"])
    docker = (
        "sudo docker rm -f experion-enn4-w192d16 >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-w192d16 --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data_d16 /w/enn4_w192d16 "
        "--epochs 15 --lr 0.0008 --width 192 "
        "--resume /w/enn4_ccrl12m_w192/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    say(log, "training; waiting")
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-w192d16"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_w192d16/best.bin", str(OUT)])
    say(log, f"wrote {OUT} (no match; self-play owns the Mac)")


if __name__ == "__main__":
    main()
