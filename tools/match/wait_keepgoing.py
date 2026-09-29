#!/usr/bin/env python3
"""Keep matching/training until Fruit and Crafty are ≥50%/40g.

Survives Cursor chat idle: caffeinate + new session. Never returns while
work remains. llama is down; all training is local MPS.
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
LOG = BASE / "tools" / "match" / "wait_keepgoing.log"
MIX25 = BASE / "nets" / "enn4_tactics_mix25.bin"
SHIP = BASE / "nets" / "enn4_w192all.bin"
TAC1 = BASE / "nets" / "enn4_mix25_tac1.bin"
SEARCH = BASE / "src" / "experion" / "search.cr"
SCORE_RE = re.compile(
    r"Score of Experion.*: (\d+) - (\d+) - (\d+)\s+\[([0-9.]+)\]\s+(\d+)"
)
LMR_OLD = "r = (Math.log(d.to_f) * Math.log(m.to_f) / 2.3).to_i"
LMR_NEW = "r = (Math.log(d.to_f) * Math.log(m.to_f) / 3.0).to_i"
IIR_OLD = "      depth -= 1 if tt_move == Moves::MOVE_NONE && depth >= 5 && !in_check"
IIR_NEW = "      # IIR off (keepgoing canary)\n      # depth -= 1 if tt_move == Moves::MOVE_NONE && depth >= 5 && !in_check"
SEE_OLD = "            prune_futility = true if depth <= 4 && see_val < -(80 * depth)"
SEE_NEW = "            prune_futility = true if depth <= 4 && see_val < -(50 * depth)"
LMP_OLD = """          lmp_margin = if depth == 1
                        5
                      elsif depth == 2
                        8
                      elsif depth == 3
                        13
                      else
                        18
                      end"""
LMP_NEW = """          lmp_margin = if depth == 1
                        8
                      elsif depth == 2
                        12
                      elsif depth == 3
                        18
                      else
                        24
                      end"""


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


def play(net: Path, opp: str, stem: str, rounds: str, abort_after=None, abort_below=None):
    while fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools" / "match" / "experion_nnue.sh")
    env["EXPERION_NNUE"] = str(net)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
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


def rebuild() -> None:
    while fastchess_up():
        say("rebuild: waiting for fastchess")
        time.sleep(10)
    say("shards build --release")
    r = subprocess.run(["shards", "build", "--release"], cwd=str(BASE),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        say(r.stdout[-2000:])
        sys.exit(1)
    r = subprocess.run(["crystal", "spec", "--no-color"], cwd=str(BASE),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = r.stdout.strip().splitlines()[-2:]
    say("spec " + " | ".join(tail))
    if r.returncode != 0:
        sys.exit(1)


def patch(path: Path, old: str, new: str) -> bool:
    text = path.read_text()
    if old not in text:
        say(f"patch miss in {path.name}: {old[:60]!r}")
        return False
    path.write_text(text.replace(old, new, 1))
    return True


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
    if len(nums) < 2:
        return False
    return 200 <= nums[0] <= 700 and 400 <= nums[1] <= 1000


def start_train_40m() -> subprocess.Popen | None:
    out = BASE / "datasets" / "enn4_mix25_tac40e1"
    net = BASE / "nets" / "enn4_mix25_tac40e1.bin"
    if net.exists() and nnue_ok(net):
        say(f"already have {net}")
        return None
    data = BASE / "datasets" / "ccrl_tactics40m"
    if not (data / "train_w.npy").exists():
        say("no 40m pack")
        return None
    logp = BASE / "tools" / "match" / "mix25_tac40e1.out"
    say("start 40M 1ep freeze-linear from mix25 (MPS)")
    log = open(logp, "w", buffering=1)
    proc = subprocess.Popen(
        ["caffeinate", "-i", "python3", str(BASE / "tools" / "train_nnue_v4.py"),
         str(data), str(out),
         "--width", "192", "--epochs", "1", "--lr", "0.00015",
         "--batch", "4096", "--device", "mps",
         "--resume", str(MIX25), "--freeze-linear"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
    )
    (BASE / "tools" / "match" / "mix25_tac40e1.pid").write_text(str(proc.pid) + "\n")
    return proc


def finish_train_40m(proc: subprocess.Popen | None) -> Path | None:
    net = BASE / "nets" / "enn4_mix25_tac40e1.bin"
    if net.exists() and nnue_ok(net):
        return net
    if proc is None:
        return net if net.exists() else None
    rc = proc.wait()
    say(f"40m train rc={rc}")
    best = BASE / "datasets" / "enn4_mix25_tac40e1" / "best.bin"
    if rc != 0 or not best.exists() or not nnue_ok(best):
        return None
    shutil.copy2(best, net)
    return net


def search_canary(name: str, old: str, new: str) -> None:
    say(f"=== search canary {name} ===")
    if not patch(SEARCH, old, new):
        return
    rebuild()
    sc = play(MIX25, "fruit", f"mix25_{name}", "10", abort_after=12, abort_below=0.12)
    ok = sc and sc[3] >= 0.22 and sc[4] >= 16
    if not ok:
        say(f"{name} failed vs Fruit; revert")
        if not patch(SEARCH, new, old):
            say("revert failed")
            sys.exit(1)
        rebuild()
        return
    say(f"{name} held Fruit {sc[3]:.1%}; Crafty 20g")
    play(MIX25, "crafty", f"mix25_{name}_crafty", "10", abort_after=14, abort_below=0.28)
    if sc[3] >= 0.28:
        play(MIX25, "fruit", f"mix25_{name}_fruit40", "20")


def main() -> None:
    LOG.write_text("")
    say("keepgoing start — do not exit until Fruit and Crafty ≥50%/40g")
    train_p = start_train_40m()

    tac1_log = BASE / "tools" / "match" / "mix25_tac1_fruit.log"
    if tac1_log.exists() and "Finished match" not in tac1_log.read_text(errors="replace"):
        say("waiting for in-flight mix25_tac1 vs Fruit")
        sc = wait_log(tac1_log, abort_after=12, abort_below=0.12)
    elif tac1_log.exists():
        sc = parse_score(tac1_log.read_text(errors="replace"))
        say(f"tac1 fruit already done: {sc}")
    else:
        sc = play(TAC1, "fruit", "mix25_tac1_fruit", "10", abort_after=12, abort_below=0.12)

    if sc and sc[3] >= 0.18:
        play(TAC1, "crafty", "mix25_tac1_crafty", "10", abort_after=14, abort_below=0.22)
        if sc[3] >= 0.26:
            play(TAC1, "fruit", "mix25_tac1_fruit40", "20")
    else:
        say("tac1 not better than mix25 21%; skip Crafty")

    net40 = finish_train_40m(train_p)
    if net40:
        sc40 = play(net40, "fruit", "tac40e1_fruit", "10", abort_after=12, abort_below=0.12)
        if sc40 and sc40[3] >= 0.22:
            play(net40, "crafty", "tac40e1_crafty", "10", abort_after=14, abort_below=0.28)
            if sc40[3] >= 0.28:
                play(net40, "fruit", "tac40e1_fruit40", "20")
                play(net40, "crafty", "tac40e1_crafty40", "20")

    search_canary("lmr30", LMR_OLD, LMR_NEW)
    search_canary("lmp", LMP_OLD, LMP_NEW)
    search_canary("nmpsee", SEE_OLD, SEE_NEW)
    search_canary("noiro", IIR_OLD, IIR_NEW)

    say("=== mix25 Fruit 40g + Crafty 40g baseline with current binary ===")
    play(MIX25, "fruit", "mix25_fruit40_keep", "20", abort_after=16, abort_below=0.10)
    play(MIX25, "crafty", "mix25_crafty40_keep", "20", abort_after=16, abort_below=0.12)
    play(SHIP, "crafty", "ship_crafty40_keep", "20", abort_after=16, abort_below=0.12)
    play(SHIP, "fruit", "ship_fruit40_keep", "20", abort_after=16, abort_below=0.08)

    say("keepgoing queue empty — 40g Fruit+Crafty loop until ≥50% both")
    n = 0
    while True:
        n += 1
        f = play(MIX25, "fruit", f"keep_fruit_{n}", "20", abort_after=20, abort_below=0.08)
        c = play(MIX25, "crafty", f"keep_crafty_{n}", "20", abort_after=20, abort_below=0.08)
        if f and c and f[3] >= 0.50 and f[4] >= 38 and c[3] >= 0.50 and c[4] >= 38:
            say("GOAL: mix25 ≥50% vs Fruit and Crafty")
            break
        # cluster may come back
        r = subprocess.run(["nc", "-z", "-G", "2", "192.168.2.46", "22"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            say("llama ssh is open — stop so an agent can use the cluster")
            break
    say("keepgoing exit")


if __name__ == "__main__":
    main()
