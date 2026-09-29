#!/usr/bin/env python3
"""Mix data12m+d16 and train two w192 fine-tunes in parallel. No local match."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_gpu_now.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"


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
    run(log, ["rsync", "-az",
              str(BASE / "tools" / "train_nnue_v4.py"),
              str(BASE / "tools" / "mix_nnue_npy.py"),
              f"{HOST}:{REMOTE}/"])
    mix = (
        "python /w/mix_nnue_npy.py /w/data12m /w/data_d16 "
        "/w/mixed_w192d16 --upsample-rest 1"
    )
    run(log, ["ssh", HOST,
              "sudo docker run --rm -v /home/joey/experion_train:/w "
              "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
              "bash -lc '" + mix + "'"])
    d16mix = (
        "sudo docker rm -f experion-enn4-w192d16mix >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-w192d16mix --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_w192d16 /w/enn4_w192d16mix "
        "--epochs 15 --lr 0.0008 --width 192 "
        "--resume /w/enn4_ccrl12m_w192/best.pt --freeze-linear"
    )
    wdl20 = (
        "sudo docker rm -f experion-enn4-w192wdl20 >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-w192wdl20 --gpus device=1 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data12m /w/enn4_w192wdl20 "
        "--epochs 15 --lr 0.0008 --width 192 --device cuda:0 "
        "--eval-weight 0.8 --wdl-weight 0.2 "
        "--resume /w/enn4_ccrl12m_w192/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, d16mix])
    run(log, ["ssh", HOST, wdl20])
    say(log, "training d16mix on 3060 and wdl20 on 1650")
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-w192d16mix experion-enn4-w192wdl20"])
    run(log, ["rsync", "-az",
              f"{HOST}:{REMOTE}/enn4_w192d16mix/best.bin",
              str(BASE / "nets" / "enn4_w192d16mix.bin")])
    run(log, ["rsync", "-az",
              f"{HOST}:{REMOTE}/enn4_w192wdl20/best.bin",
              str(BASE / "nets" / "enn4_w192wdl20.bin")])
    say(log, "wrote enn4_w192d16mix.bin and enn4_w192wdl20.bin")


if __name__ == "__main__":
    main()
