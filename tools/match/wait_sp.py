#!/usr/bin/env python3
"""After mix25 d8 scored gen: pack, freeze-linear 1ep, head blend, match.

Does not rematch mix25 forever. Extra 2000-game gens if Fruit stays <18%.
Cluster poll after the queue.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "wait_sp.log"
MIX25 = BASE / "nets" / "enn4_tactics_mix25.bin"
SCORE_RE = re.compile(
    r"Score of Experion.*: (\d+) - (\d+) - (\d+)\s+\[([0-9.]+)\]\s+(\d+)"
)


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


def parse_score(text: str):
    last = None
    for ln in text.splitlines():
        m = SCORE_RE.search(ln)
        if m:
            w, l, d, pct, n = m.groups()
            last = (int(w), int(l), int(d), float(pct), int(n), ln)
    return last


def fastchess_up() -> bool:
    return subprocess.run(["pgrep", "-x", "fastchess"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def wait_log(path: Path, abort_after=None, abort_below=None, timeout_s=3600):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if path.exists():
            text = path.read_text(errors="replace")
            if "Finished match" in text:
                return parse_score(text)
            sc = parse_score(text)
            if sc and abort_after and abort_below is not None and sc[4] >= abort_after and sc[3] < abort_below:
                say(f"abort {path.name}: {sc[5]}")
                subprocess.run(["pkill", "-x", "fastchess"], check=False)
                time.sleep(2)
                return sc
        if not path.exists() and not fastchess_up() and time.time() - t0 > 30:
            say(f"no fastchess and no {path.name}")
            return None
        time.sleep(15)
    say(f"timeout {path.name}")
    subprocess.run(["pkill", "-x", "fastchess"], check=False)
    return parse_score(path.read_text(errors="replace")) if path.exists() else None


def play(net: Path, opp: str, stem: str, rounds: str, abort_after=None, abort_below=None, threads: str = "4"):
    logp = BASE / "tools" / "match" / f"{stem}.log"
    if logp.exists():
        text = logp.read_text(errors="replace")
        if "Finished match" in text:
            sc = parse_score(text)
            if sc:
                say(f"skip {stem} {sc[0]}-{sc[1]}-{sc[2]} = {sc[3]:.1%} / {sc[4]}g")
                return sc
        sc = parse_score(text)
        if sc and sc[4] >= 12:
            say(f"skip {stem} aborted {sc[0]}-{sc[1]}-{sc[2]} = {sc[3]:.1%} / {sc[4]}g")
            return sc
    while fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(net)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = threads
    say(f"{int(rounds)*2}g 10+0.1 vs {opp} net={net.name} stem={stem}")
    subprocess.run(
        ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
         "10+0.1", rounds, opp, stem],
        env=env, cwd=str(BASE), check=True,
    )
    sc = wait_log(BASE / "tools" / "match" / f"{stem}.log", abort_after, abort_below)
    if sc:
        say(f"{stem} {sc[0]}-{sc[1]}-{sc[2]} = {sc[3]:.1%} / {sc[4]}g")
    else:
        say(f"{stem}: no score")
    return sc


def nnue_ok(net: Path) -> bool:
    rook = "4k3/8/8/8/8/8/R7/4K3 w - - 0 1"
    queen = "4k3/8/8/8/8/8/Q7/4K3 w - - 0 1"
    r = subprocess.run(
        ["python3", str(BASE / "tools" / "nnue_check.py"), str(net), rook, queen],
        cwd=str(BASE), capture_output=True, text=True,
    )
    nums = []
    for ln in r.stdout.splitlines():
        try:
            nums.append(int(ln.split()[0]))
        except ValueError:
            pass
    say(f"material {net.name} {nums}")
    return len(nums) >= 2 and 200 <= nums[0] <= 700 and 400 <= nums[1] <= 1000


def fruit_then_crafty(net: Path, stem: str, fruit_bar=0.18):
    sc = play(net, "fruit", f"{stem}_fruit", "10", abort_after=12, abort_below=0.12)
    if sc and sc[3] >= fruit_bar:
        play(net, "crafty", f"{stem}_crafty", "10", abort_after=14, abort_below=0.18)
        if sc[3] >= 0.26:
            play(net, "fruit", f"{stem}_fruit40", "20", abort_after=18, abort_below=0.15)
            play(net, "crafty", f"{stem}_crafty40", "20", abort_after=16, abort_below=0.18)
    return sc


def cluster_up() -> bool:
    r = subprocess.run(["nc", "-z", "-G", "2", "192.168.2.46", "22"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def concat_parts(txt: Path) -> bool:
    parts = sorted(txt.parent.glob(txt.name + ".*"))
    parts = [p for p in parts if p.name.rsplit(".", 1)[-1].isdigit()]
    if not parts:
        return False
    n = 0
    with open(txt, "w") as out:
        for p in parts:
            with open(p, errors="replace") as f:
                for line in f:
                    if line.strip():
                        out.write(line if line.endswith("\n") else line + "\n")
                        n += 1
    say(f"concat {len(parts)} parts → {txt.name} {n} lines")
    return n > 0


def wait_gendata(txt: Path | None = None, pidp: Path | None = None,
                 timeout_s: int = 8 * 3600) -> Path | None:
    txt = txt or (BASE / "datasets" / "selfplay_mix25_book.txt")
    pidp = pidp or (BASE / "tools" / "match" / "gendata_mix25_book.pid")
    t0 = time.time()
    last_hb = 0.0
    while time.time() - t0 < timeout_s:
        pid_alive = False
        if pidp.exists():
            pid = pidp.read_text().strip()
            pid_alive = subprocess.run(["ps", "-p", pid], stdout=subprocess.DEVNULL).returncode == 0
        if not pid_alive:
            if txt.exists() and txt.stat().st_size > 50_000:
                say(f"gendata done {txt} {txt.stat().st_size} bytes")
                return txt
            if concat_parts(txt) and txt.stat().st_size > 50_000:
                return txt
            say(f"gendata died pid={pidp}")
            return None
        now = time.time()
        if now - last_hb >= 120:
            sz = 0
            for p in txt.parent.glob(txt.name + ".*"):
                if p.name.rsplit(".", 1)[-1].isdigit():
                    try:
                        sz += p.stat().st_size
                    except OSError:
                        pass
            say(f"gendata still running {txt.name} parts={sz}B elapsed={int(now - t0)}s")
            last_hb = now
        time.sleep(20)
    say("gendata timeout")
    return None


def launch_selfplay(games: int, depth: int, txt: Path, stem: str) -> Path:
    env = os.environ.copy()
    env["EXPERION_SELFPLAY_NNUE"] = "1"
    env["EXPERION_NNUE"] = str(MIX25)
    env["EXPERION_BLEND"] = "100"
    env["EXPERION_OPENINGS"] = str(BASE / "datasets" / "match_openings.fen")
    env["EXPERION_SP_NODES"] = "80000"
    say(f"launch selfplay {games}g d{depth} → {txt.name}")
    subprocess.run(
        ["python3", str(BASE / "tools" / "match" / "run_selfplay_detached.py"),
         str(games), str(depth), str(txt), "4", stem],
        env=env, cwd=str(BASE), check=True,
    )
    return BASE / "tools" / "match" / f"{stem}.pid"


def pack_train_blend(txt: Path, tag: str) -> list[Path]:
    src = txt
    if tag.startswith("mix25_x"):
        extras = []
        for name in ("selfplay_mix25_book.txt", "selfplay_mix25_x1.txt"):
            p = BASE / "datasets" / name
            if p.exists() and p.stat().st_size > 50_000 and p.resolve() != txt.resolve():
                extras.append(p)
        if extras:
            merged = txt.with_name(txt.stem + "_merged.txt")
            if not (merged.exists() and merged.stat().st_size > txt.stat().st_size):
                say(f"merge {[p.name for p in extras]} + {txt.name} → {merged.name}")
                with open(merged, "wb") as out:
                    for p in extras + [txt]:
                        with open(p, "rb") as f:
                            shutil.copyfileobj(f, out)
            src = merged
    npy = BASE / "datasets" / f"{tag}_npy"
    if not (npy / "train_w.npy").exists():
        say(f"pack {src.name} → {npy.name}")
        r = subprocess.run(
            ["python3", str(BASE / "tools" / "prepare_selfplay.py"), str(src), str(npy)],
            cwd=str(BASE),
        )
        if r.returncode != 0:
            say("pack failed")
            return []
    out = BASE / "datasets" / f"enn4_{tag}"
    best = out / "best.bin"
    epochs = 3 if tag.startswith("mix25_x") else 1
    lr = "0.0005" if tag.startswith("mix25_x") else "0.0001"
    if not (best.exists() and nnue_ok(best)):
        say(f"train mix25 freeze-linear {epochs}ep on {tag}")
        logp = BASE / "tools" / "match" / f"{tag}_train.out"
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
        if rc != 0 or not best.exists() or not nnue_ok(best):
            say(f"train {tag} failed or material bad")
            return []
    nets = []
    full = BASE / "nets" / f"enn4_{tag}.bin"
    shutil.copy2(best, full)
    # Blends first: full FT of mix25 on self-play failed 40g Fruit (x1 30%→8%).
    for t, ttag in ((0.25, "h25"), (0.15, "h15")):
        mixed = BASE / "nets" / f"enn4_{tag}_{ttag}.bin"
        subprocess.run(
            ["python3", str(BASE / "tools" / "mix_enn4.py"),
             str(MIX25), str(full), str(mixed), "--t", str(t)],
            check=True,
        )
        if nnue_ok(mixed):
            nets.append(mixed)
    nets.append(full)
    return nets


def train_from_npy(npy: Path, tag: str) -> list[Path]:
    out = BASE / "datasets" / f"enn4_{tag}"
    best = out / "best.bin"
    epochs = 2
    lr = "0.00012"
    if not (best.exists() and nnue_ok(best)):
        say(f"train mix25 freeze-linear {epochs}ep on {tag}")
        logp = BASE / "tools" / "match" / f"{tag}_train.out"
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
        if rc != 0 or not best.exists() or not nnue_ok(best):
            say(f"train {tag} failed or material bad")
            return []
    nets = []
    full = BASE / "nets" / f"enn4_{tag}.bin"
    shutil.copy2(best, full)
    for t, ttag in ((0.25, "h25"), (0.15, "h15")):
        mixed = BASE / "nets" / f"enn4_{tag}_{ttag}.bin"
        subprocess.run(
            ["python3", str(BASE / "tools" / "mix_enn4.py"),
             str(MIX25), str(full), str(mixed), "--t", str(t)],
            check=True,
        )
        if nnue_ok(mixed):
            nets.append(mixed)
    return nets


def train_ccrl_tail() -> list[Path]:
    pgn = BASE / "datasets" / "ccrl4040" / "CCRL-4040-commented.[2436759].pgn"
    data = BASE / "datasets" / "ccrl_qtac_skip6e9"
    if not (data / "train_w.npy").exists():
        say("pack CCRL skip 6e9 d12 quiets+tactics 8M")
        logp = BASE / "tools" / "match" / "pack_qtac_skip6e9.out"
        log = open(logp, "w", buffering=1)
        r = subprocess.run(
            ["caffeinate", "-i", "python3", str(BASE / "tools" / "prepare_ccrl.py"),
             str(pgn), str(data),
             "--positions", "8000000", "--skip-bytes", "6000000000",
             "--min-depth", "12", "--include-tactics"],
            cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        )
        if r.returncode != 0:
            say("ccrl pack failed")
            return []
    return train_from_npy(data, "mix25_skip6")


def match_nets(nets: list[Path], fruit_bar: float = 0.18) -> bool:
    held = False
    for net in nets:
        sc = fruit_then_crafty(net, net.stem.replace("enn4_", ""), fruit_bar=fruit_bar)
        if sc and sc[3] >= 0.45 and sc[4] >= 36:
            held = True
    return held


def main() -> None:
    say("wait_sp start — match-book self-play d10, pack, FT, blend, match, extra gens if Fruit <18%")
    txt = wait_gendata()
    if not txt or not txt.exists():
        say("no selfplay txt")
        sys.exit(1)

    # 600g 1ep lr=1e-4 did not move mix25 (material 299/526, Fruit 4.2%/12g).
    # Do not spend another 40g matching the clone blends.
    say("skip mix25_spd8 Fruit rematch — 1ep FT was a no-op")
    held = False

    play(MIX25, "fruit", "mix25_t1_fruit", "10", abort_after=12, abort_below=0.12, threads="1")

    # x1 20g Fruit 30% was noise: 40g confirm 8% and Crafty 0/14.
    say("skip mix25_x1 rematch — 30%/20g failed 40g confirm")
    # x2 h25 0/12, h15 22.5%/20g = mix25 noise. No more mix25 self-play FT.
    say("skip mix25_x2 rematch — SP FT does not beat mix25 Fruit 21%")
    extra = 2
    while not held and extra < 3:
        extra += 1
        if cluster_up():
            say("llama ssh is open — stop extra gens")
            break
        if extra >= 3:
            held = match_nets(train_ccrl_tail())
            continue
        tag = f"mix25_x{extra}"
        txt2 = BASE / "datasets" / f"selfplay_{tag}.txt"
        stem = f"gendata_{tag}"
        pidp = BASE / "tools" / "match" / f"{stem}.pid"
        if not (txt2.exists() and txt2.stat().st_size > 50_000):
            launch_selfplay(1500, 10, txt2, stem)
        w = wait_gendata(txt2, pidp, timeout_s=10 * 3600)
        if not w or not w.exists():
            say(f"extra gen {tag} failed")
            continue
        held = match_nets(pack_train_blend(w, tag))

    say("wait_sp queue empty — poll cluster")
    last_hb = 0.0
    while True:
        if cluster_up():
            say("llama ssh is open")
            break
        now = time.time()
        if now - last_hb >= 300:
            say("cluster still down; waiter alive")
            last_hb = now
        time.sleep(60)
    say("wait_sp exit")


if __name__ == "__main__":
    main()
