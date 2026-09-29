#!/usr/bin/env python3
"""After the FICS Fruit queue: WDL-heavy FICS, Glaurung labels, ProbCut canary.

Does not rematch mix25. Survives by being launched detached.
"""
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
LOG = HERE / "wait_next_elo.log"
wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def fics_queue_done() -> bool:
    p = HERE / "wait_fruit_fics.log"
    if not p.exists():
        return False
    text = p.read_text(errors="replace")
    return "cluster poll" in text or "llama still down" in text or "llama is up" in text


def fruit_held() -> bool:
    for log in HERE.glob("mix25_fics25*_fruit.log"):
        sc = wsp.parse_score(log.read_text(errors="replace"))
        if sc and sc[3] >= 0.26 and sc[4] >= 18:
            say(f"FICS net held Fruit {sc[3]:.1%} / {sc[4]}g in {log.name}")
            return True
    return False


def train_blend(npy: Path, tag: str, epochs: int, lr: str,
                eval_w: str, wdl_w: str):
    out = BASE / "datasets" / f"enn4_{tag}"
    best = out / "best.bin"
    if not (best.exists() and wsp.nnue_ok(best)):
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


def wait_no_fastchess() -> None:
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(20)


def rebuild_probcut() -> bool:
    say("rebuild bin/experion with ProbCut")
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE),
    )
    say(f"shards build rc={r.returncode}")
    return r.returncode == 0


def teacher_engine() -> Path | None:
    sf = Path("/opt/homebrew/bin/stockfish")
    if sf.exists():
        return sf
    g = BASE / "tools" / "match" / "ladder" / "glaurung22"
    return g if g.exists() else None


def label_teacher() -> Path | None:
    src = BASE / "datasets" / "selfplay_mix25_x2_merged.txt"
    eng = teacher_engine()
    if not src.exists() or eng is None:
        say("missing selfplay txt or teacher engine")
        return None
    tag = "sf19" if "stockfish" in eng.name.lower() else "glaurung"
    txt = BASE / "datasets" / f"{tag}_x2.txt"
    npy = BASE / "datasets" / f"{tag}_x2_npy"
    depth = "8" if tag == "sf19" else "6"
    limit = "120000" if tag == "sf19" else "80000"
    if not (txt.exists() and txt.stat().st_size > 500_000):
        say(f"label {limit} FENs with {eng.name} d{depth}")
        logp = HERE / f"label_{tag}.out"
        log = open(logp, "w", buffering=1)
        r = subprocess.run(
            ["caffeinate", "-i", "python3", "-u", str(BASE / "tools" / "label_uci.py"),
             str(src), str(txt),
             "--engine", str(eng), "--depth", depth, "--threads", "1",
             "--hash", "64", "--limit", limit],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        )
        if r.returncode != 0 or not txt.exists():
            say(f"{tag} label failed")
            return None
    if not (npy / "train_w.npy").exists():
        say(f"pack {tag}_x2")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(txt), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say(f"{tag} pack failed")
            return None
    return npy


def main() -> None:
    say("wait_next_elo: sf19h (8ep lr=1e-3) then ProbCut")
    wait_no_fastchess()
    npy = BASE / "datasets" / "sf19_x2_npy"
    if npy.exists():
        nets = train_blend(npy, "mix25_sf19h", epochs=8, lr="0.001",
                           eval_w="0.85", wdl_w="0.15")
        for net in nets:
            wsp.fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=0.18)
            lp = HERE / f"{net.stem.replace('enn4_', '')}_fruit.log"
            sc = wsp.parse_score(lp.read_text(errors="replace")) if lp.exists() else None
            if sc and sc[3] >= 0.45 and sc[4] >= 36:
                say("sf19h cleared Fruit")
                return

    wait_no_fastchess()
    if rebuild_probcut():
        r = subprocess.run(["crystal", "spec"], cwd=str(BASE), capture_output=True, text=True)
        tail = (r.stdout or "")[-400:]
        say(f"spec rc={r.returncode} {tail.splitlines()[-3:]}")
        if r.returncode == 0:
            wsp.play(MIX25, "fruit", "mix25_probcut_fruit", "10",
                     abort_after=12, abort_below=0.12)
            # revert on fail
            logp = HERE / "mix25_probcut_fruit.log"
            sc = wsp.parse_score(logp.read_text(errors="replace")) if logp.exists() else None
            if not sc or sc[3] < 0.18:
                say("ProbCut failed Fruit — revert search.cr ProbCut")
                subprocess.run(["git", "checkout", "--", "src/experion/search.cr"], cwd=str(BASE))
                subprocess.run(["caffeinate", "-i", "shards", "build", "--release"], cwd=str(BASE))
                say("reverted ProbCut and rebuilt")
            else:
                say("ProbCut held Fruit — keep it, Crafty next")
                wsp.play(MIX25, "crafty", "mix25_probcut_crafty", "10",
                         abort_after=14, abort_below=0.18)

    say("wait_next_elo queue finished; cluster poll")
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
