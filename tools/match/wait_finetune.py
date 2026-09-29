#!/usr/bin/env python3
"""After self-play npy exists, mix with CCRL data3m on llama and fine-tune ENN4.

Detached: Cursor abort must not kill this. Does not train on crafty_pure.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
NPY = BASE / "datasets" / "selfplay_npy" / "manifest.json"
LOG = BASE / "tools" / "match" / "finetune.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def run(log, cmd, **kw):
    say(log, "+ " + " ".join(cmd))
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)
    return r


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for packed self-play npy")
    while not NPY.exists():
        time.sleep(20)
    say(log, f"found {NPY}")
    run(log, ["rsync", "-az", str(BASE / "datasets" / "selfplay_npy") + "/",
              f"{HOST}:{REMOTE}/selfplay_npy/"])
    run(log, ["rsync", "-az",
              str(BASE / "tools" / "train_nnue_v4.py"),
              str(BASE / "tools" / "mix_nnue_npy.py"),
              f"{HOST}:{REMOTE}/"])
    cc = (
        "BASE=/w/session_20260908/data3m; "
        "test -f /w/data12m/manifest.json && BASE=/w/data12m; "
        "python /w/mix_nnue_npy.py $BASE /w/selfplay_npy "
        "/w/mixed_ccrl_selfplay --upsample-rest 4"
    )
    mix_docker = (
        "sudo docker run --rm -v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "bash -lc '" + cc + "'"
    )
    run(log, ["ssh", HOST, mix_docker])
    run(log, ["ssh", HOST,
              "sudo docker wait experion-enn4-w512 >/dev/null 2>&1 || true; "
              "sudo docker wait experion-enn4-12m >/dev/null 2>&1 || true"])
    docker = (
        "sudo docker rm -f experion-enn4-mix >/dev/null 2>&1 || true; "
        "RESUME=/w/enn4_ccrl/best.pt; "
        "test -f /w/enn4_ccrl12m/best.pt && RESUME=/w/enn4_ccrl12m/best.pt; "
        "sudo docker run -d --name experion-enn4-mix --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_ccrl_selfplay /w/enn4_mix "
        "--epochs 20 --lr 0.0008 --resume $RESUME"
    )
    run(log, ["ssh", HOST, docker])
    say(log, "fine-tune container started; waiting for it to exit")
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-mix"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_mix/best.bin",
              str(BASE / "nets" / "enn4_mix.bin")])
    say(log, "wrote nets/enn4_mix.bin")


if __name__ == "__main__":
    main()
