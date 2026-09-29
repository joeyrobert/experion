#!/usr/bin/env python3
"""If scored-walk Fruit dies: mix those labels with CCRL quiets and retry.

Random-walk-only FT may overfit junk positions. 400k quiets + scored as a
regularizer. Waits for wait_scored to finish matching. Does not rematch mix25.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402
import wait_after_sf as was  # noqa: E402

BASE = wsp.BASE
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_scored_mix.log"
wsp.LOG = LOG
was.LOG = LOG

Q8 = BASE / "datasets" / "ccrl_quiet8m"
SC = BASE / "datasets" / "scored_mix25_d8_npy"
OUT = BASE / "datasets" / "scored_quiet_npy"
SLOG = HERE / "wait_scored.log"


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say
was.say = say


def scored_done() -> bool:
    if not SLOG.exists():
        return False
    t = SLOG.read_text(errors="replace")
    return (
        "scored done" in t
        or "scored cleared Fruit" in t
        or "scored gen failed" in t
        or "llama still down" in t
        or "llama is up" in t
    )


def scored_cleared() -> bool:
    return SLOG.exists() and "scored cleared Fruit" in SLOG.read_text(errors="replace")


def mix() -> Path | None:
    if (OUT / "train_w.npy").exists():
        return OUT
    if not (SC / "train_w.npy").exists() or not (Q8 / "train_w.npy").exists():
        say("missing scored or quiet8m npy")
        return None
    say("concat 400k quiets + scored walks")
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260918)
    counts = {}
    for split, cap in (("train", 400_000), ("val", 20_000)):
        wa = np.load(Q8 / f"{split}_w.npy")
        ba = np.load(Q8 / f"{split}_b.npy")
        ta = np.load(Q8 / f"{split}_targets.npy")
        if len(wa) > cap:
            ix = rng.choice(len(wa), size=cap, replace=False)
            wa, ba, ta = wa[ix], ba[ix], ta[ix]
        wb = np.load(SC / f"{split}_w.npy")
        bb = np.load(SC / f"{split}_b.npy")
        tb = np.load(SC / f"{split}_targets.npy")
        w = np.concatenate([wa, wb])
        b = np.concatenate([ba, bb])
        t = np.concatenate([ta, tb])
        perm = rng.permutation(len(w))
        np.save(OUT / f"{split}_w.npy", w[perm])
        np.save(OUT / f"{split}_b.npy", b[perm])
        np.save(OUT / f"{split}_targets.npy", t[perm])
        counts[split] = int(len(perm))
        say(f"  {split}: quiet {len(wa)} + scored {len(wb)} = {len(perm)}")
    (OUT / "manifest.json").write_text(json.dumps({"positions": counts}, indent=2))
    return OUT


def main() -> None:
    say("wait_scored_mix: after scored Fruit queue")
    last_hb = 0.0
    while not scored_done():
        now = time.time()
        if now - last_hb >= 120:
            extra = ""
            parts = list((BASE / "datasets").glob("scored_mix25_d8.txt*"))
            sz = sum(p.stat().st_size for p in parts)
            extra = f" scored_bytes={sz}"
            say(f"waiting for scored queue{extra}")
            last_hb = now
        time.sleep(20)
    if scored_cleared():
        say("scored already cleared Fruit")
        return
    npy = mix()
    nets = was.train_blend(npy, "mix25_scoredq", 6, "0.0003") if npy else []
    if nets and was.match_nets(nets, "scoredq"):
        say("scoredq cleared Fruit")
        return
    say("scored_mix done; cluster poll")
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
