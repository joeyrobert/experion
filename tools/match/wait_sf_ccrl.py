#!/usr/bin/env python3
"""After ProbCut Crafty: SF-label a fresh CCRL window, hard FT mix25, match Fruit."""
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
LOG = HERE / "wait_sf_ccrl.log"
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


def train_blend(npy: Path, tag: str, epochs: int, lr: str,
                eval_w: str, wdl_w: str):
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
             "--eval-weight", eval_w, "--wdl-weight", wdl_w],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )
        rc = proc.wait()
        say(f"train {tag} rc={rc}")
        if rc != 0 or not best.exists() or not wsp.nnue_ok(best):
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
        if wsp.nnue_ok(mixed):
            nets.append(mixed)
    if wsp.nnue_ok(full):
        nets.append(full)
    return nets


def main() -> None:
    say("wait_sf_ccrl: waiting for fastchess")
    wait_no_fastchess()
    pgn = BASE / "datasets" / "ccrl4040" / "CCRL-4040-commented.[2436759].pgn"
    txt = BASE / "datasets" / "ccrl_sf_skip3e9.txt"
    labeled = BASE / "datasets" / "ccrl_sf19.txt"
    npy = BASE / "datasets" / "ccrl_sf19_npy"
    if not (txt.exists() and txt.stat().st_size > 1_000_000):
        say("extract 200k CCRL FENs skip 3e9 d12 q+t")
        logp = HERE / "extract_ccrl_sf.out"
        log = open(logp, "w", buffering=1)
        r = subprocess.run(
            ["caffeinate", "-i", "python3", "-u", str(BASE / "tools" / "extract_ccrl_txt.py"),
             str(pgn), str(txt),
             "--positions", "200000", "--skip-bytes", "3000000000",
             "--min-depth", "12", "--include-tactics"],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        )
        if r.returncode != 0 or not txt.exists():
            say("ccrl extract failed")
            return
    if not (labeled.exists() and labeled.stat().st_size > 1_000_000):
        say("SF-label 150k CCRL FENs d8")
        logp = HERE / "label_ccrl_sf19.out"
        log = open(logp, "w", buffering=1)
        r = subprocess.run(
            ["caffeinate", "-i", "python3", "-u", str(BASE / "tools" / "label_uci.py"),
             str(txt), str(labeled),
             "--engine", "/opt/homebrew/bin/stockfish",
             "--depth", "8", "--threads", "1", "--hash", "64",
             "--limit", "150000"],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        )
        if r.returncode != 0 or not labeled.exists():
            say("sf label failed")
            return
    if not (npy / "train_w.npy").exists():
        say("pack ccrl_sf19")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(labeled), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("pack failed")
            return
    nets = train_blend(npy, "mix25_ccrlsf", epochs=8, lr="0.001",
                       eval_w="0.85", wdl_w="0.15")
    for net in nets:
        wsp.fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
        lp = HERE / f"{net.stem.replace('enn4_', '')}_fruit.log"
        sc = wsp.parse_score(lp.read_text(errors="replace")) if lp.exists() else None
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            say("ccrlsf cleared Fruit")
            return
    say("ccrlsf queue done; cluster poll")
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
