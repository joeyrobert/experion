#!/usr/bin/env python3
"""Local (MPS) pipeline: match-opening self-play → pack → freeze-linear FT.

llama is down. Labels include captures/checks (|score|<8000). Resume mix25,
freeze the linear PSQT so material cannot collapse, then 25% head-blend back
onto mix25. Fruit 20g first (baseline 21%), then Crafty if Fruit holds.
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_matchbook.log"
PID_PATH = BASE / "tools" / "match" / "selfplay_matchbook.pid"
TXT = BASE / "datasets" / "selfplay_matchbook.txt"
NPY = BASE / "datasets" / "selfplay_matchbook_npy"
MIXED = BASE / "datasets" / "mixed_matchbook"
TRAIN = BASE / "datasets" / "enn4_matchbook"
SHIP = BASE / "nets" / "enn4_w192all.bin"
MIX25 = BASE / "nets" / "enn4_tactics_mix25.bin"
OUT_NET = BASE / "nets" / "enn4_matchbook.bin"
W192 = BASE / "datasets" / "selfplay_w192_npy"

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
ROOK = "4k3/8/8/8/8/8/R7/4K3 w - - 0 1"
QUEEN = "4k3/8/8/8/8/8/Q7/4K3 w - - 0 1"
SCORE_RE = re.compile(
    r"Score of Experion.*: (\d+) - (\d+) - (\d+)\s+\[([0-9.]+)\]\s+(\d+)"
)


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


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def load_enn4(path: Path):
    raw = path.read_bytes()
    if raw[:4] != b"ENN4":
        raise ValueError(f"{path} is not ENN4")
    width, = struct.unpack_from("<I", raw, 4)
    count = 768 * (width + 1)
    w1 = np.frombuffer(raw, dtype="<i2", count=count, offset=8).reshape(768, width + 1).copy()
    bias = np.frombuffer(raw, dtype="<i2", count=width, offset=8 + 2 * count).copy()
    output = np.frombuffer(raw, dtype="<i2", count=2 * width,
                           offset=8 + 2 * (count + width)).copy()
    return width, w1, bias, output


def save_enn4(path: Path, width, w1, bias, output) -> None:
    with open(path, "wb") as f:
        f.write(b"ENN4" + struct.pack("<I", width))
        f.write(np.clip(np.rint(w1), -32767, 32767).astype("<i2").tobytes())
        f.write(np.clip(np.rint(bias), -32767, 32767).astype("<i2").tobytes())
        f.write(np.clip(np.rint(output), -32767, 32767).astype("<i2").tobytes())


def peek_material(path: Path) -> dict[str, float]:
    width, w1, _, _ = load_enn4(path)
    lin = w1[:, width].astype(np.float32) / 8.0
    names = "PNBRQK"
    out = {}
    for i, n in enumerate(names):
        out[n] = float(lin[i * 64:(i + 1) * 64].mean())
    return out


def nnue_cp(log, net: Path, fen: str) -> str:
    r = subprocess.run(
        ["python3", str(BASE / "tools" / "nnue_check.py"), str(net), fen],
        cwd=str(BASE), capture_output=True, text=True,
    )
    line = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "?"
    say(log, f"eval {net.name} {fen.split()[0][:16]}… {line}")
    return line


def parse_score(text: str):
    last = None
    for ln in text.splitlines():
        m = SCORE_RE.search(ln)
        if m:
            w, l, d, pct, n = m.groups()
            last = (int(w), int(l), int(d), float(pct), int(n), ln)
    return last


def play(log, net: Path, opp: str, stem: str, rounds: str,
         abort_after: int | None, abort_below: float | None) -> tuple:
    while True:
        r = subprocess.run(["pgrep", "-x", "fastchess"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            break
        say(log, "waiting for fastchess")
        time.sleep(20)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(net)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, f"{int(rounds)*2}g 10+0.1 vs {opp} net={net.name}")
    run(log, ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
              "10+0.1", rounds, opp, stem], env=env, cwd=str(BASE))
    path = BASE / "tools" / "match" / f"{stem}.log"
    while True:
        if not path.exists():
            time.sleep(10)
            continue
        text = path.read_text(errors="replace")
        if "Finished match" in text:
            break
        sc = parse_score(text)
        if sc and abort_after and abort_below is not None and sc[4] >= abort_after and sc[3] < abort_below:
            say(log, f"abort {stem}: {sc[5]}")
            subprocess.run(["pkill", "-x", "fastchess"], check=False)
            time.sleep(2)
            return sc
        time.sleep(20)
    text = path.read_text(errors="replace")
    sc = parse_score(text)
    say(log, sc[5] if sc else f"{stem}: no score")
    return sc


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "matchbook self-play → local MPS freeze-linear")

    pid = int(PID_PATH.read_text().strip())
    say(log, f"waiting for selfplay pid {pid}")
    while alive(pid):
        time.sleep(20)
    say(log, "selfplay process exited")
    if not TXT.exists() or TXT.stat().st_size < 50_000:
        say(log, f"missing or tiny output: {TXT}")
        sys.exit(1)

    say(log, f"packing {TXT} -> {NPY}")
    run(log, ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(TXT), str(NPY)],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)

    mix_cmd = ["python3", str(BASE / "tools" / "mix_nnue_npy.py")]
    if W192.exists():
        mix_cmd += [str(W192), str(NPY), str(MIXED), "--upsample-rest", "8"]
    else:
        mix_cmd += [str(NPY), str(MIXED), "--upsample-rest", "1"]
    run(log, mix_cmd, cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)

    device = "mps"
    try:
        import torch
        if not torch.backends.mps.is_available():
            device = "cpu"
            say(log, "MPS unavailable, training on CPU")
    except Exception as e:
        say(log, f"torch import failed: {e}")
        sys.exit(1)

    TRAIN.mkdir(parents=True, exist_ok=True)
    run(log, [
        "python3", str(BASE / "tools" / "train_nnue_v4.py"),
        str(MIXED), str(TRAIN),
        "--width", "192", "--epochs", "4", "--lr", "0.0004",
        "--batch", "4096", "--device", device,
        "--resume", str(MIX25), "--freeze-linear",
    ], cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)

    best = TRAIN / "best.bin"
    if not best.exists():
        say(log, "missing best.bin")
        sys.exit(1)

    # Freeze-linear keeps the PSQT mean near textbook 500/900; collapse
    # shows up in K+R/K+Q evals, not those means (the old R>450 gate
    # false-aborted a healthy 280/542 net).
    import shutil
    shutil.copy2(best, OUT_NET)
    say(log, f"shipped freeze-linear FT {OUT_NET}")
    rook_cp = int(nnue_cp(log, OUT_NET, ROOK).split()[0])
    queen_cp = int(nnue_cp(log, OUT_NET, QUEEN).split()[0])
    nnue_cp(log, OUT_NET, START)
    if rook_cp < 200 or rook_cp > 700 or queen_cp < 400 or queen_cp > 1000:
        say(log, f"position material collapsed rook={rook_cp} queen={queen_cp}")
        sys.exit(1)

    match_only()


def match_only() -> None:
    log = open(LOG, "a", buffering=1)
    if not OUT_NET.exists():
        say(log, f"missing {OUT_NET}")
        sys.exit(1)
    say(log, f"matching {OUT_NET.name} Fruit then Crafty (fair STM clocks)")
    fruit = play(log, OUT_NET, "fruit", "matchbook_fruit", "10",
                 abort_after=12, abort_below=0.10)
    if fruit:
        say(log, f"Fruit {fruit[0]}-{fruit[1]}-{fruit[2]} = {fruit[3]:.1%} / {fruit[4]}g")
        if fruit[3] >= 0.26 and fruit[4] < 40:
            fruit = play(log, OUT_NET, "fruit", "matchbook_fruit40", "20",
                         abort_after=None, abort_below=None)
            if fruit:
                say(log, f"Fruit40 {fruit[0]}-{fruit[1]}-{fruit[2]} = {fruit[3]:.1%} / {fruit[4]}g")

    # Crafty always: fair clocks are new evidence even if Fruit is flat.
    crafty = play(log, OUT_NET, "crafty", "matchbook_crafty", "10",
                  abort_after=14, abort_below=0.28)
    if crafty:
        say(log, f"Crafty {crafty[0]}-{crafty[1]}-{crafty[2]} = {crafty[3]:.1%} / {crafty[4]}g")
        if crafty[3] >= 0.48 and crafty[4] < 40:
            crafty = play(log, OUT_NET, "crafty", "matchbook_crafty40", "20",
                          abort_after=None, abort_below=None)
            if crafty:
                say(log, f"Crafty40 {crafty[0]}-{crafty[1]}-{crafty[2]} = {crafty[3]:.1%} / {crafty[4]}g")
    say(log, "matchbook pipeline done")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--match-only":
        match_only()
    else:
        main()
