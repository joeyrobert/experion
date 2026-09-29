#!/usr/bin/env python3
"""SF-label Experion-vs-Fruit match FENs, hard FT mix25, weak blends first."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_sf_fruit.log"
wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def wait_no_fastchess() -> None:
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(20)


def train_blend(npy: Path, tag: str, epochs: int, lr: str):
    out = BASE / "datasets" / f"enn4_{tag}"
    best = out / "best.bin"
    if not (best.exists() and wsp.nnue_ok(best)):
        say(f"train mix25 freeze-linear {epochs}ep on {tag} lr={lr}")
        logp = HERE / f"{tag}_train.out"
        log = open(logp, "w", buffering=1)
        proc = subprocess.Popen(
            ["caffeinate", "-i", "python3", str(BASE / "tools" / "train_nnue_v4.py"),
             str(npy), str(out),
             "--width", "192", "--epochs", str(epochs), "--lr", lr,
             "--batch", "4096", "--device", "mps",
             "--resume", str(MIX25), "--freeze-linear",
             "--eval-weight", "0.85", "--wdl-weight", "0.15"],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )
        rc = proc.wait()
        say(f"train {tag} rc={rc}")
        if rc != 0 or not best.exists() or not wsp.nnue_ok(best):
            say(f"train {tag} failed")
            return []
    nets = []
    full = BASE / "nets" / f"enn4_{tag}.bin"
    subprocess.run(["cp", str(best), str(full)], check=True)
    for t, ttag in ((0.10, "h10"), (0.15, "h15"), (0.25, "h25")):
        mixed = BASE / "nets" / f"enn4_{tag}_{ttag}.bin"
        subprocess.run(
            ["python3", str(BASE / "tools" / "mix_enn4.py"),
             str(MIX25), str(full), str(mixed), "--t", str(t)],
            check=True,
        )
        if wsp.nnue_ok(mixed):
            nets.append(mixed)
    return nets


def main() -> None:
    say("wait_sf_fruit: SF-label Fruit-match FENs")
    wait_no_fastchess()
    src = BASE / "datasets" / "fruit_match.txt"
    labeled = BASE / "datasets" / "fruit_sf19.txt"
    npy = BASE / "datasets" / "fruit_sf19_npy"
    if not src.exists():
        say("no fruit_match.txt")
        return
    if not (labeled.exists() and labeled.stat().st_size > 500_000):
        say("SF-label fruit_match FENs d8")
        logp = HERE / "label_fruit_sf19.out"
        log = open(logp, "w", buffering=1)
        r = subprocess.run(
            ["caffeinate", "-i", "python3", "-u", str(BASE / "tools" / "label_uci.py"),
             str(src), str(labeled),
             "--engine", "/opt/homebrew/bin/stockfish",
             "--depth", "8", "--threads", "1", "--hash", "64"],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        )
        if r.returncode != 0 or not labeled.exists():
            say("label failed")
            return
    if not (npy / "train_w.npy").exists():
        say("pack fruit_sf19")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"),
             str(labeled), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("pack failed")
            return
    nets = train_blend(npy, "mix25_fruitsf", epochs=8, lr="0.001")
    for net in nets:
        sc = wsp.fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            say("fruitsf cleared Fruit")
            return
    say("fruitsf done; cluster poll")
    last = 0.0
    while True:
        if wsp.cluster_up():
            say("llama is up")
            return
        now = time.time()
        if now - last >= 300:
            say("llama still down")
            last = now
        time.sleep(60)


if __name__ == "__main__":
    main()
