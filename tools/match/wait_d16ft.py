#!/usr/bin/env python3
"""Fine-tune enn4_ccrl12m on the depth>=16 quiet pack already on llama.

No Crafty labels. Copies nets/enn4_d16ft.bin and plays Crafty after fastchess
is free.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_d16ft.log"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"
OUT = BASE / "nets" / "enn4_d16ft.bin"


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


def match_score(path: Path) -> str:
    text = path.read_text(errors="replace") if path.exists() else ""
    lines = [ln for ln in text.splitlines() if "Score of Experion" in ln]
    return lines[-1] if lines else ""


def wait_fastchess(log) -> None:
    while True:
        r = subprocess.run(["pgrep", "-x", "fastchess"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return
        say(log, "waiting for fastchess to finish")
        time.sleep(20)


def main() -> None:
    log = open(LOG, "w", buffering=1)
    run(log, ["rsync", "-az", str(BASE / "tools" / "train_nnue_v4.py"),
              f"{HOST}:{REMOTE}/train_nnue_v4.py"])
    docker = (
        "sudo docker rm -f experion-enn4-d16ft >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-d16ft --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/data_d16 /w/enn4_d16ft "
        "--epochs 15 --lr 0.0008 --resume /w/enn4_ccrl12m/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    say(log, "training; waiting")
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-d16ft"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_d16ft/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")
    wait_fastchess(log)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(OUT)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, "Crafty 20g with d16ft net")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "10", "crafty", "crafty_d16ft"], env=env, cwd=str(BASE))
    crafty = BASE / "tools" / "match" / "crafty_d16ft.log"
    while True:
        if crafty.exists() and "Finished match" in crafty.read_text(errors="replace"):
            break
        time.sleep(20)
    say(log, match_score(crafty))
    say(log, "d16ft pipeline done")


if __name__ == "__main__":
    main()
