#!/usr/bin/env python3
"""Scale SF-CCRL labels to ~750k, hard FT mix25, weak blends first."""
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
LOG = HERE / "wait_sf_scale.log"
wsp.LOG = LOG
PGN = BASE / "datasets" / "ccrl4040" / "CCRL-4040-commented.[2436759].pgn"


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


def train_blend(npy: Path, tag: str):
    out = BASE / "datasets" / f"enn4_{tag}"
    best = out / "best.bin"
    if not (best.exists() and wsp.nnue_ok(best)):
        say(f"train mix25 freeze-linear 8ep on {tag} lr=0.0005")
        logp = HERE / f"{tag}_train.out"
        log = open(logp, "w", buffering=1)
        proc = subprocess.Popen(
            ["caffeinate", "-i", "python3", str(BASE / "tools" / "train_nnue_v4.py"),
             str(npy), str(out),
             "--width", "192", "--epochs", "8", "--lr", "0.0005",
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
    say("wait_sf_scale: 600k more CCRL FENs + SF d8")
    wait_no_fastchess()
    extra = BASE / "datasets" / "ccrl_sf_skip4e9.txt"
    extra_sf = BASE / "datasets" / "ccrl_sf19_b.txt"
    merged = BASE / "datasets" / "ccrl_sf19_750k.txt"
    npy = BASE / "datasets" / "ccrl_sf19_750k_npy"
    old = BASE / "datasets" / "ccrl_sf19.txt"
    if not (extra.exists() and extra.stat().st_size > 2_000_000):
        say("extract 600k CCRL skip 4e9 d12 q+t")
        log = open(HERE / "extract_ccrl_sf_b.out", "w", buffering=1)
        r = subprocess.run(
            ["caffeinate", "-i", "python3", "-u", str(BASE / "tools" / "extract_ccrl_txt.py"),
             str(PGN), str(extra),
             "--positions", "600000", "--skip-bytes", "4000000000",
             "--min-depth", "12", "--include-tactics"],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        )
        if r.returncode != 0 or not extra.exists():
            say("extract failed")
            return
    if not (extra_sf.exists() and extra_sf.stat().st_size > 20_000_000):
        say("SF-label 600k d8 (4× stockfish)")
        parts = []
        jobs = []
        for i, skip in enumerate((0, 150000, 300000, 450000)):
            outp = BASE / "datasets" / f"ccrl_sf19_b{i}.txt"
            parts.append(outp)
            if outp.exists() and outp.stat().st_size > 5_000_000:
                continue
            log = open(HERE / f"label_ccrl_sf19_b{i}.out", "w", buffering=1)
            jobs.append(subprocess.Popen(
                ["caffeinate", "-i", "python3", "-u", str(BASE / "tools" / "label_uci.py"),
                 str(extra), str(outp),
                 "--engine", "/opt/homebrew/bin/stockfish",
                 "--depth", "8", "--threads", "1", "--hash", "32",
                 "--skip", str(skip), "--limit", "150000"],
                cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            ))
        rc = 0
        for j in jobs:
            rc |= j.wait()
        if rc != 0 or any(not p.exists() for p in parts):
            say("parallel label failed")
            return
        say("concat 4 parts")
        with open(extra_sf, "wb") as out:
            for p in parts:
                with open(p, "rb") as f:
                    out.write(f.read())
    if not (merged.exists() and merged.stat().st_size > 10_000_000):
        say("merge old 150k + new 600k")
        with open(merged, "wb") as out:
            for p in (old, extra_sf):
                if p.exists():
                    with open(p, "rb") as f:
                        out.write(f.read())
    if not (npy / "train_w.npy").exists():
        say("pack 750k")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(merged), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("pack failed")
            return
    nets = train_blend(npy, "mix25_sf750")
    for net in nets:
        sc = wsp.fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            say("sf750 cleared Fruit")
            return
    say("sf750 done; cluster poll")
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
