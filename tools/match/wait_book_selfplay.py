#!/usr/bin/env python3
"""After Fruit finishes: rebuild, NNUE self-play from match openings, pack, fine-tune, Crafty."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "bookplay.log"
FRUIT = BASE / "tools" / "match" / "fruit_nnue12m.log"
TXT = BASE / "datasets" / "selfplay_book.txt"
NPY = BASE / "datasets" / "selfplay_book_npy"
OPEN = BASE / "datasets" / "match_openings.fen"
NET = BASE / "nets" / "enn4_ccrl12m.bin"
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
    say(log, "waiting for Fruit match to finish")
    while True:
        if FRUIT.exists() and "Finished match" in FRUIT.read_text(errors="replace"):
            break
        time.sleep(15)
    say(log, "Fruit done; building release")
    run(log, ["shards", "build", "--release"], cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)
    env = os.environ.copy()
    env["EXPERION_SELFPLAY_NNUE"] = "1"
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["EXPERION_OPENINGS"] = str(OPEN)
    say(log, "NNUE book self-play 4000 d8 t4")
    run(
        log,
        [str(BASE / "bin" / "experion"), "gendata-selfplay", "4000", "8", str(TXT), "4"],
        cwd=str(BASE),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    say(log, "packing")
    run(log, ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(TXT), str(NPY)], cwd=str(BASE))
    run(log, ["rsync", "-az", str(NPY) + "/", f"{HOST}:{REMOTE}/selfplay_book_npy/"])
    run(log, ["rsync", "-az", str(BASE / "tools" / "train_nnue_v4.py"),
              str(BASE / "tools" / "mix_nnue_npy.py"), f"{HOST}:{REMOTE}/"])
    run(log, ["ssh", HOST,
              "while ! test -s /home/joey/experion_train/enn4_tactics/best.pt; do sleep 20; done; "
              "sudo docker wait experion-enn4-tactics >/dev/null 2>&1 || true"])
    mix = (
        "python /w/mix_nnue_npy.py /w/data12m /w/selfplay_book_npy "
        "/w/mixed_book --upsample-rest 8"
    )
    run(log, ["ssh", HOST,
              "sudo docker run --rm -v /home/joey/experion_train:/w "
              "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
              "bash -lc '" + mix + "'"])
    docker = (
        "sudo docker rm -f experion-enn4-book >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-book --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_book /w/enn4_book "
        "--epochs 15 --lr 0.0006 --resume /w/enn4_qt/best.pt"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-book"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_book/best.bin",
              str(BASE / "nets" / "enn4_book.bin")])
    say(log, "launching Crafty with book net")
    env2 = os.environ.copy()
    env2["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env2["EXPERION_NNUE"] = str(BASE / "nets" / "enn4_book.bin")
    env2["EXPERION_BLEND"] = "100"
    env2["CONC"] = "1"
    env2["THREADS"] = "4"
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "20", "crafty", "crafty_book"], env=env2, cwd=str(BASE))
    say(log, "Crafty book match detached")


if __name__ == "__main__":
    main()
