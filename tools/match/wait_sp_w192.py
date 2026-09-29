#!/usr/bin/env python3
"""After w192 match-book self-play: pack, mix data12m+1x, fine-tune w192, Crafty.

No Crafty labels. Mix 1x only (6x d10 self-play was weaker than 12m).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_sp_w192.log"
PLAY = BASE / "tools" / "match" / "selfplay_w192.log"
TXT = BASE / "datasets" / "selfplay_w192.txt"
NPY = BASE / "datasets" / "selfplay_w192_npy"
HOST = "joey@192.168.2.46"
REMOTE = "/home/joey/experion_train"
OUT = BASE / "nets" / "enn4_w192sp.bin"


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


def score_pct(path: Path):
    line = match_score(path)
    if not line:
        return None
    m = re.search(r"\[([0-9.]+)\]", line)
    if m:
        return float(m.group(1)) * 100.0
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", line)
    if not m:
        return None
    w, l, d = map(int, m.groups())
    n = w + l + d
    return 100.0 * (w + 0.5 * d) / n if n else None


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


def wait_fastchess(log) -> None:
    while True:
        r = subprocess.run(["pgrep", "-x", "fastchess"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return
        say(log, "waiting for fastchess to finish")
        time.sleep(20)


def play_crafty(log, net: Path, stem: str) -> None:
    wait_fastchess(log)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(net)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, f"Crafty 20g {stem} net={net.name}")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", "10", "crafty", stem], env=env, cwd=str(BASE))
    path = BASE / "tools" / "match" / f"{stem}.log"
    while True:
        if path.exists() and "Finished match" in path.read_text(errors="replace"):
            break
        time.sleep(20)
    say(log, match_score(path))


def main() -> None:
    log = open(LOG, "a", buffering=1)
    say(log, "waiting for w192 match-book self-play")
    while True:
        text = PLAY.read_text(errors="replace") if PLAY.exists() else ""
        if "generated " in text:
            break
        parts = list(TXT.parent.glob(TXT.name + ".*"))
        if parts:
            sizes = sum(p.stat().st_size for p in parts)
            say(log, f"parts {len(parts)} bytes={sizes}")
        time.sleep(30)
    extras = [
        (BASE / "nets" / "enn4_w192d16.bin", "crafty_w192d16"),
        (BASE / "nets" / "enn4_w192d16mix.bin", "crafty_w192d16mix"),
        (BASE / "nets" / "enn4_w192wdl20.bin", "crafty_w192wdl20"),
        (BASE / "nets" / "enn4_w192fics.bin", "crafty_w192fics"),
        (BASE / "nets" / "enn4_w192all.bin", "crafty_w192all"),
    ]
    for net, stem in extras:
        if not net.exists():
            say(log, f"skip {stem}: {net.name} missing")
            continue
        say(log, f"self-play done; Crafty sample {stem} net={net.name}")
        play_crafty(log, net, stem)
        pct = score_pct(BASE / "tools" / "match" / f"{stem}.log")
        if pct is None:
            say(log, f"{stem}: no score line, skip confirm")
            continue
        if pct >= 45.0:
            say(log, f"{stem} {pct:.1f}% >= 45; confirmation 20g")
            play_crafty(log, net, stem + "b")
        else:
            say(log, f"{stem} {pct:.1f}% < 45; skip confirmation")
    concat_parts(log)
    say(log, "packing")
    run(log, ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(TXT), str(NPY)],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)
    run(log, ["rsync", "-az", str(NPY) + "/", f"{HOST}:{REMOTE}/selfplay_w192_npy/"])
    run(log, ["rsync", "-az", str(BASE / "tools" / "train_nnue_v4.py"),
              str(BASE / "tools" / "mix_nnue_npy.py"), f"{HOST}:{REMOTE}/"])
    mix = (
        "python /w/mix_nnue_npy.py /w/data12m /w/selfplay_w192_npy "
        "/w/mixed_w192sp --upsample-rest 1"
    )
    run(log, ["ssh", HOST,
              "sudo docker run --rm -v /home/joey/experion_train:/w "
              "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
              "bash -lc '" + mix + "'"])
    docker = (
        "sudo docker rm -f experion-enn4-w192sp >/dev/null 2>&1 || true; "
        "sudo docker run -d --name experion-enn4-w192sp --gpus device=0 "
        "-v /home/joey/experion_train:/w "
        "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime "
        "python /w/train_nnue_v4.py /w/mixed_w192sp /w/enn4_w192sp "
        "--epochs 15 --lr 0.0008 --width 192 "
        "--resume /w/enn4_ccrl12m_w192/best.pt --freeze-linear"
    )
    run(log, ["ssh", HOST, docker])
    run(log, ["ssh", HOST, "sudo docker wait experion-enn4-w192sp"])
    run(log, ["rsync", "-az", f"{HOST}:{REMOTE}/enn4_w192sp/best.bin", str(OUT)])
    say(log, f"wrote {OUT}")
    say(log, "Crafty 20g with w192sp net")
    play_crafty(log, OUT, "crafty_w192sp")
    pct = score_pct(BASE / "tools" / "match" / "crafty_w192sp.log")
    if pct is not None and pct >= 45.0:
        say(log, f"w192sp {pct:.1f}% >= 45; confirmation 20g")
        play_crafty(log, OUT, "crafty_w192spb")
    else:
        say(log, f"w192sp {pct} < 45; skip confirmation")
    say(log, "w192sp pipeline done")


if __name__ == "__main__":
    main()
