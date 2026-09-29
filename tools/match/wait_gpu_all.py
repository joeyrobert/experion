#!/usr/bin/env python3
"""Mix data12m+d16+fics 1x and fine-tune w192. No local match."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_gpu_all.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"
OUT = BASE / "nets" / "enn4_w192all.bin"


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
    run(log, ["ssh", HOST,
              "sudo rm -rf /home/joey/experion_train/mixed_w192d16 "
              "/home/joey/experion_train/mixed_w192fics"])
    mix = (
        "python /w/mix_nnue_npy.py /w/data12m /w/data_d16 /w/data_fics "
        "/w/mixed_w192all --upsample-rest 1"
    )
    run(log, ["ssh", HOST,
              "sudo docker run --rm -v /home/joey/experion_train:/w "
              "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
              "bash -lc '" + mix + "'"])
    docker = (
        "sudo docker rm -f experion-enn4-w192all >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-w192all --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_w192all /w/enn4_w192all "
        "--epochs 15 --lr 0.0008 --width 192 "
        "--resume /w/enn4_ccrl12m_w192/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-w192all"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_w192all/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")


if __name__ == "__main__":
    main()
