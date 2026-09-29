#!/usr/bin/env python3
"""After FICS npy exists: mix 1x into data12m, fine-tune w192, copy net. No match."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_fics.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"
OUT = BASE / "nets" / "enn4_w192fics.bin"


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
    say(log, "waiting for data_fics/manifest.json")
    while True:
        r = subprocess.run(
            ["ssh", HOST, "test -s /home/joey/experion_train/data_fics/manifest.json"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            break
        time.sleep(30)
    say(log, "waiting for other ENN4 GPU trains to finish")
    while True:
        r = subprocess.run(
            ["ssh", HOST,
             "sudo docker ps --format '{{.Names}}' | "
             "grep -E 'experion-enn4-w192d16mix|experion-enn4-w192wdl20' || true"],
            capture_output=True, text=True,
        )
        names = (r.stdout or "").strip()
        if not names:
            break
        say(log, f"gpu busy: {names}")
        time.sleep(30)
    mix = (
        "python /w/mix_nnue_npy.py /w/data12m /w/data_fics "
        "/w/mixed_w192fics --upsample-rest 1"
    )
    run(log, ["ssh", HOST,
              "sudo docker run --rm -v /home/joey/experion_train:/w "
              "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
              "bash -lc '" + mix + "'"])
    docker = (
        "sudo docker rm -f experion-enn4-w192fics >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-w192fics --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_w192fics /w/enn4_w192fics "
        "--epochs 15 --lr 0.0008 --width 192 "
        "--resume /w/enn4_ccrl12m_w192/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-w192fics"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_w192fics/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")


if __name__ == "__main__":
    main()
