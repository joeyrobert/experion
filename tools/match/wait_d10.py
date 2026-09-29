#!/usr/bin/env python3
"""After large d10 self-play: pack, mix 12m+6x, fine-tune 12m, Crafty 20g then 20g more.

No Crafty labels. Do not resume tactics/qt nets.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_d10.log"
PLAY = BASE / "tools" / "match" / "selfplay_d10.log"
TXT = BASE / "datasets" / "selfplay_d10.txt"
NPY = BASE / "datasets" / "selfplay_d10_npy"
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


def concat_parts(log) -> None:
    parts = sorted(TXT.parent.glob(TXT.name + ".*"))
    if TXT.exists() and TXT.stat().st_size > 1000:
        say(log, f"joined file exists {TXT.stat().st_size} bytes")
        return
    if not parts:
        say(log, "no self-play parts")
        sys.exit(1)
    n = 0
    with TXT.open("w") as out:
        for p in parts:
            if p.suffix == ".txt":
                continue
            for line in p.open(errors="replace"):
                if line.strip():
                    out.write(line if line.endswith("\n") else line + "\n")
                    n += 1
    say(log, f"concatenated {len(parts)} parts -> {n} lines")


def match_score(path: Path) -> str:
    text = path.read_text(errors="replace") if path.exists() else ""
    lines = [ln for ln in text.splitlines() if "Score of Experion" in ln]
    return lines[-1] if lines else ""


def main() -> None:
    log = open(LOG, "a", buffering=1)
    say(log, "waiting for d10 self-play to finish")
    while True:
        text = PLAY.read_text(errors="replace") if PLAY.exists() else ""
        if "generated " in text:
            break
        parts = list(TXT.parent.glob(TXT.name + ".*"))
        if parts:
            sizes = sum(p.stat().st_size for p in parts)
            say(log, f"parts {len(parts)} bytes={sizes}")
        time.sleep(30)
    concat_parts(log)
    say(log, "packing")
    run(log, ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(TXT), str(NPY)],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)
    run(log, ["rsync", "-az", str(NPY) + "/", f"{HOST}:{REMOTE}/selfplay_d10_npy/"])
    run(log, ["rsync", "-az", str(BASE / "tools" / "train_nnue_v4.py"),
              str(BASE / "tools" / "mix_nnue_npy.py"), f"{HOST}:{REMOTE}/"])
    mix = (
        "python /w/mix_nnue_npy.py /w/data12m /w/selfplay_d10_npy "
        "/w/mixed_d10 --upsample-rest 6"
    )
    run(log, ["ssh", HOST,
              "sudo docker run --rm -v /home/joey/experion_train:/w "
              "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
              "bash -lc '" + mix + "'"])
    docker = (
        "sudo docker rm -f experion-enn4-d10 >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-d10 --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_d10 /w/enn4_d10 "
        "--epochs 20 --lr 0.001 --resume /w/enn4_ccrl12m/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-d10"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_d10/best.bin",
              str(BASE / "nets" / "enn4_d10.bin")])
    env2 = os.environ.copy()
    env2["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env2["EXPERION_NNUE"] = str(BASE / "nets" / "enn4_d10.bin")
    env2["EXPERION_BLEND"] = "100"
    env2["CONC"] = "1"
    env2["THREADS"] = "4"
    say(log, "Crafty 20g with d10 net")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "10", "crafty", "crafty_d10"], env=env2, cwd=str(BASE))
    crafty = BASE / "tools" / "match" / "crafty_d10.log"
    while True:
        if crafty.exists() and "Finished match" in crafty.read_text(errors="replace"):
            break
        time.sleep(20)
    say(log, match_score(crafty))
    say(log, "Crafty confirmation 20g")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "10", "crafty", "crafty_d10b"], env=env2, cwd=str(BASE))
    crafty_b = BASE / "tools" / "match" / "crafty_d10b.log"
    while True:
        if crafty_b.exists() and "Finished match" in crafty_b.read_text(errors="replace"):
            break
        time.sleep(20)
    say(log, match_score(crafty_b))
    say(log, "d10 pipeline done")


if __name__ == "__main__":
    main()
