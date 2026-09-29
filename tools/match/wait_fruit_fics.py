#!/usr/bin/env python3
"""New local Elo levers: Fruit-match PGN labels, then FICS 2025 WDL.

Does not rematch mix25. Cluster poll after the queue.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wait_sp import (  # noqa: E402
    BASE,
    MIX25,
    cluster_up,
    fruit_then_crafty,
    nnue_ok,
    say,
)

HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_fruit_fics.log"


def _say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


# wait_sp.say writes wait_sp.log; redirect by monkeypatching after import
import wait_sp as _wsp  # noqa: E402

_wsp.LOG = LOG
_wsp.say = _say
say = _say


def train_blend(npy: Path, tag: str, epochs: int, lr: str,
                eval_w: str, wdl_w: str) -> list[Path]:
    out = BASE / "datasets" / f"enn4_{tag}"
    best = out / "best.bin"
    if not (best.exists() and nnue_ok(best)):
        say(f"train mix25 freeze-linear {epochs}ep on {tag} lr={lr} wdl={wdl_w}")
        logp = HERE / f"{tag}_train.out"
        log = open(logp, "w", buffering=1)
        proc = subprocess.Popen(
            ["caffeinate", "-i", "python3", str(BASE / "tools" / "train_nnue_v4.py"),
             str(npy), str(out),
             "--width", "192", "--epochs", str(epochs), "--lr", lr,
             "--batch", "4096", "--device", "mps",
             "--resume", str(MIX25), "--freeze-linear",
             "--eval-weight", eval_w, "--wdl-weight", wdl_w],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )
        rc = proc.wait()
        say(f"train {tag} rc={rc}")
        if rc != 0 or not best.exists() or not nnue_ok(best):
            say(f"train {tag} failed or material bad")
            return []
    nets = []
    full = BASE / "nets" / f"enn4_{tag}.bin"
    subprocess.run(["cp", str(best), str(full)], check=True)
    for t, ttag in ((0.25, "h25"), (0.15, "h15")):
        mixed = BASE / "nets" / f"enn4_{tag}_{ttag}.bin"
        subprocess.run(
            ["python3", str(BASE / "tools" / "mix_enn4.py"),
             str(MIX25), str(full), str(mixed), "--t", str(t)],
            check=True,
        )
        if nnue_ok(mixed):
            nets.append(mixed)
    if nnue_ok(full):
        nets.append(full)
    return nets


def extract_fruit() -> Path | None:
    txt = BASE / "datasets" / "fruit_match.txt"
    npy = BASE / "datasets" / "fruit_match_npy"
    pgn = HERE / "games.pgn"
    if not (txt.exists() and txt.stat().st_size > 200_000):
        say("extract Fruit match PGNs")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "extract_fruit_pgn.py"), str(pgn), str(txt)],
            cwd=str(BASE),
        )
        if r.returncode != 0 or not txt.exists():
            say("fruit extract failed")
            return None
    if not (npy / "train_w.npy").exists():
        say("pack fruit_match")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(txt), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("fruit pack failed")
            return None
    return npy


def pack_fics() -> Path | None:
    npy = BASE / "datasets" / "fics2025_npy"
    bz2 = BASE / "datasets" / "ficsgamesdb_2025_chess_movetimes_4339706.pgn.bz2"
    if (npy / "train_w.npy").exists():
        say("fics npy already packed")
        return npy
    if not bz2.exists():
        say("no FICS 2025 bz2")
        return None
    say("pack FICS 2025 1.5M quiets, mix25 eval labels")
    logp = HERE / "pack_fics2025.out"
    log = open(logp, "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "python3", str(BASE / "tools" / "pack_fics_nnue.py"),
         str(bz2), str(npy),
         "--pt", str(MIX25), "--width", "192",
         "--positions", "1500000", "--device", "mps"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    if r.returncode != 0 or not (npy / "train_w.npy").exists():
        say("fics pack failed")
        return None
    return npy


def poll_cluster() -> None:
    say("cluster poll")
    last = 0.0
    while True:
        if cluster_up():
            say("llama is up — stop this waiter and train on the cluster")
            return
        now = time.time()
        if now - last >= 300:
            say("llama still down")
            last = now
        time.sleep(60)


def main() -> None:
    say("fruit-match + FICS 2025 waiter starting")
    npy = extract_fruit()
    if npy is not None:
        nets = train_blend(npy, "mix25_fruitpgn", epochs=4, lr="0.0003",
                           eval_w="0.55", wdl_w="0.45")
        for net in nets:
            fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
    else:
        say("skip fruit-pgn train")

    fics = pack_fics()
    if fics is not None:
        nets = train_blend(fics, "mix25_fics25", epochs=2, lr="0.00012",
                           eval_w="0.70", wdl_w="0.30")
        for net in nets:
            fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
    else:
        say("skip fics train")

    poll_cluster()


if __name__ == "__main__":
    main()
