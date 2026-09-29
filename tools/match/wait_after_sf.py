#!/usr/bin/env python3
"""After the 750k SF queue: regularized mix (CCRL quiets + SF) then CCRL-opening SP.

SF-only FT overfit a lucky 20g twice. Mix ~1.5M CCRL-native quiets with the
750k SF labels so the specialist cannot forget mix25's quiet prior. Prep/train
on MPS while sf750 still owns fastchess. Then Fruit, then self-play from
CCRL FENs (not the 300-line match book). Does not rematch mix25.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_after_sf.log"
wsp.LOG = LOG

Q8 = BASE / "datasets" / "ccrl_quiet8m"
SF = BASE / "datasets" / "ccrl_sf19_750k_npy"
MIX = BASE / "datasets" / "ccrl_mixreg_npy"
OPEN = BASE / "datasets" / "ccrl_openings.fen"
SKIP4 = BASE / "datasets" / "ccrl_sf_skip4e9.txt"
SP_TXT = BASE / "datasets" / "selfplay_mix25_ccrlop.txt"


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


def sf750_log() -> str:
    p = HERE / "wait_sf_scale.log"
    return p.read_text(errors="replace") if p.exists() else ""


def sf750_queue_done() -> bool:
    text = sf750_log()
    return "sf750 done" in text or "sf750 cleared Fruit" in text


def sf750_cleared() -> bool:
    return "sf750 cleared Fruit" in sf750_log()


def dump_openings(n: int = 8000) -> None:
    if OPEN.exists() and OPEN.stat().st_size > 200_000:
        return
    src = SKIP4 if SKIP4.exists() else BASE / "datasets" / "ccrl_sf19_750k.txt"
    if not src.exists():
        say(f"no FEN source for openings ({src.name})")
        return
    say(f"dump {n} CCRL FENs → {OPEN.name}")
    seen = set()
    kept = 0
    with open(src, errors="replace") as inf, open(OPEN, "w") as ouf:
        for line in inf:
            fen = line.split(";", 1)[0].strip()
            if not fen or fen in seen:
                continue
            seen.add(fen)
            ouf.write(fen + "\n")
            kept += 1
            if kept >= n:
                break
    say(f"openings {kept}")


def mix_npy(n_a: int = 1_500_000, seed: int = 20260918) -> Path | None:
    if (MIX / "train_w.npy").exists():
        return MIX
    if not (Q8 / "train_w.npy").exists() or not (SF / "train_w.npy").exists():
        say("missing quiet8m or sf750 npy")
        return None
    say(f"concat quiet8m {n_a} + sf750 → {MIX.name}")
    MIX.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    counts = {}
    for split, cap in (("train", n_a), ("val", max(n_a // 20, 40_000))):
        wa = np.load(Q8 / f"{split}_w.npy")
        ba = np.load(Q8 / f"{split}_b.npy")
        ta = np.load(Q8 / f"{split}_targets.npy")
        if len(wa) > cap:
            ix = rng.choice(len(wa), size=cap, replace=False)
            wa, ba, ta = wa[ix], ba[ix], ta[ix]
        wb = np.load(SF / f"{split}_w.npy")
        bb = np.load(SF / f"{split}_b.npy")
        tb = np.load(SF / f"{split}_targets.npy")
        w = np.concatenate([wa, wb])
        b = np.concatenate([ba, bb])
        t = np.concatenate([ta, tb])
        perm = rng.permutation(len(w))
        np.save(MIX / f"{split}_w.npy", w[perm])
        np.save(MIX / f"{split}_b.npy", b[perm])
        np.save(MIX / f"{split}_targets.npy", t[perm])
        counts[split] = int(len(perm))
        say(f"  {split}: quiet {len(wa)} + sf {len(wb)} = {len(perm)}")
    (MIX / "manifest.json").write_text(json.dumps({
        "sources": [str(Q8), str(SF)],
        "positions": counts,
        "quiet_cap": n_a,
        "seed": seed,
    }, indent=2))
    return MIX


def train_blend(npy: Path, tag: str, epochs: int, lr: str) -> list[Path]:
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
            say(f"train {tag} failed or material bad")
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


def match_nets(nets: list[Path], prefix: str) -> bool:
    wait_no_fastchess()
    for net in nets:
        sc = wsp.fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            say(f"{prefix} cleared Fruit")
            return True
    return False


def run_ccrl_selfplay() -> list[Path]:
    dump_openings()
    if not OPEN.exists():
        return []
    if not (SP_TXT.exists() and SP_TXT.stat().st_size > 50_000):
        wait_no_fastchess()
        env = os.environ.copy()
        env["EXPERION_SELFPLAY_NNUE"] = "1"
        env["EXPERION_NNUE"] = str(MIX25)
        env["EXPERION_BLEND"] = "100"
        env["EXPERION_OPENINGS"] = str(OPEN)
        env["EXPERION_SP_NODES"] = "80000"
        say("launch selfplay 2000g d8 from CCRL openings")
        subprocess.run(
            ["python3", str(HERE / "run_selfplay_detached.py"),
             "2000", "8", str(SP_TXT), "4", "gendata_mix25_ccrlop"],
            env=env, cwd=str(BASE), check=True,
        )
        txt = wsp.wait_gendata(SP_TXT, HERE / "gendata_mix25_ccrlop.pid")
        if txt is None:
            say("ccrlop selfplay failed")
            return []
    npy = BASE / "datasets" / "mix25_ccrlop_npy"
    if not (npy / "train_w.npy").exists():
        say(f"pack {SP_TXT.name}")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"),
             str(SP_TXT), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("ccrlop pack failed")
            return []
    return train_blend(npy, "mix25_ccrlop", 6, "0.0003")


def cluster_poll() -> None:
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


def main() -> None:
    say("wait_after_sf: mixreg prep while sf750 matches")
    dump_openings()
    npy = mix_npy()
    nets = train_blend(npy, "mix25_mixreg", 6, "0.0003") if npy else []
    last_hb = 0.0
    while not sf750_queue_done():
        now = time.time()
        if now - last_hb >= 120:
            h10 = HERE / "mix25_sf750_h10_fruit.log"
            extra = ""
            if h10.exists():
                sc = wsp.parse_score(h10.read_text(errors="replace"))
                if sc:
                    extra = f" sf750_h10 {sc[0]}-{sc[1]}-{sc[2]} = {sc[3]:.1%}/{sc[4]}g"
            say(f"waiting for sf750 queue{extra}")
            last_hb = now
        time.sleep(20)
    if sf750_cleared():
        say("sf750 already cleared Fruit; cluster poll")
        cluster_poll()
        return
    if nets and match_nets(nets, "mixreg"):
        cluster_poll()
        return
    say("mixreg did not clear; CCRL-opening selfplay")
    sp_nets = run_ccrl_selfplay()
    if sp_nets and match_nets(sp_nets, "ccrlop"):
        cluster_poll()
        return
    say("after_sf done; cluster poll")
    cluster_poll()


if __name__ == "__main__":
    main()
