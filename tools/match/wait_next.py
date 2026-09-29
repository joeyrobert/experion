#!/usr/bin/env python3
"""Continue after keepgoing search canaries.

Does not rematch mix25 forever (21%/5% cannot luck into 50%).
Tests blended nets, then freeze-linear FT on CCRL d16 quiets.
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
LOG = BASE / "tools" / "match" / "wait_next.log"
MIX25 = BASE / "nets" / "enn4_tactics_mix25.bin"
SHIP = BASE / "nets" / "enn4_w192all.bin"
SEARCH = BASE / "src" / "experion" / "search.cr"
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


def already(stem: str) -> bool:
    p = BASE / "tools" / "match" / f"{stem}_fruit.log"
    if not p.exists():
        return False
    sc = parse_score(p.read_text(errors="replace"))
    return bool(sc and sc[4] >= 12)


def fruit_then_crafty(net: Path, stem: str, fruit_bar=0.18, crafty_bar=0.22):
    if already(stem):
        say(f"skip {stem}, already matched")
        return parse_score((BASE / "tools" / "match" / f"{stem}_fruit.log").read_text(errors="replace"))
    sc = play(net, "fruit", f"{stem}_fruit", "10", abort_after=12, abort_below=0.12)
    if sc and sc[3] >= fruit_bar:
        play(net, "crafty", f"{stem}_crafty", "10", abort_after=14, abort_below=0.18)
        if sc[3] >= 0.26:
            play(net, "fruit", f"{stem}_fruit40", "20")
            play(net, "crafty", f"{stem}_crafty40", "20")
    return sc


def search_canary(name: str, old: str, new: str) -> None:
    say(f"=== search canary {name} ===")
    if not patch(SEARCH, old, new):
        return
    rebuild()
    net = MIX25
    sc = play(net, "fruit", f"mix25_{name}", "10", abort_after=12, abort_below=0.12)
    ok = sc and sc[3] >= 0.22 and sc[4] >= 16
    if not ok:
        say(f"{name} failed vs Fruit; revert")
        if not patch(SEARCH, new, old):
            say("revert failed")
            sys.exit(1)
        rebuild()
        return
    say(f"{name} held Fruit {sc[3]:.1%}; Crafty 20g")
    play(net, "crafty", f"mix25_{name}_crafty", "10", abort_after=14, abort_below=0.18)


def cluster_up() -> bool:
    r = subprocess.run(["nc", "-z", "-G", "2", "192.168.2.46", "22"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def wait_pack() -> Path | None:
    data = BASE / "datasets" / "ccrl_quiet8m"
    pidp = BASE / "tools" / "match" / "pack_quiet8m.pid"
    logp = BASE / "tools" / "match" / "pack_quiet8m.out"
    t0 = time.time()
    while time.time() - t0 < 8 * 3600:
        if (data / "train_w.npy").exists() and (data / "manifest.json").exists():
            say(f"pack ready {data}")
            return data
        if pidp.exists():
            pid = pidp.read_text().strip()
            r = subprocess.run(["ps", "-p", pid], stdout=subprocess.DEVNULL)
            if r.returncode != 0 and not (data / "train_w.npy").exists():
                say("pack died")
                if logp.exists():
                    say(logp.read_text()[-1500:])
                return None
        time.sleep(30)
        if cluster_up():
            say("llama ssh is open")
            return data if (data / "train_w.npy").exists() else None
    say("pack timeout")
    return None


def train_quiet(data: Path) -> Path | None:
    out = BASE / "datasets" / "enn4_mix25_quiet8m"
    net = BASE / "nets" / "enn4_mix25_quiet8m.bin"
    if net.exists() and nnue_ok(net):
        return net
    logp = BASE / "tools" / "match" / "mix25_quiet8m.out"
    say("train mix25 freeze-linear 2ep on CCRL d16 quiets")
    log = open(logp, "w", buffering=1)
    proc = subprocess.Popen(
        ["caffeinate", "-i", "python3", str(BASE / "tools" / "train_nnue_v4.py"),
         str(data), str(out),
         "--width", "192", "--epochs", "2", "--lr", "0.00012",
         "--batch", "4096", "--device", "mps",
         "--resume", str(MIX25), "--freeze-linear",
         "--eval-weight", "0.85", "--wdl-weight", "0.15"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
    )
    (BASE / "tools" / "match" / "mix25_quiet8m.pid").write_text(str(proc.pid) + "\n")
    rc = proc.wait()
    say(f"quiet train rc={rc}")
    best = out / "best.bin"
    if rc != 0 or not best.exists() or not nnue_ok(best):
        # blend 25% of trained heads onto mix25 if material drifted
        if best.exists():
            mixed = BASE / "nets" / "enn4_mix25_quiet_h25.bin"
            subprocess.run(
                ["python3", str(BASE / "tools" / "mix_enn4.py"),
                 str(MIX25), str(best), str(mixed), "--t", "0.25"],
                check=False,
            )
            if mixed.exists() and nnue_ok(mixed):
                return mixed
        return None
    shutil.copy2(best, net)
    return net


def main() -> None:
    LOG.write_text("")
    say("wait_next start — blend nets, then CCRL quiet FT")
    while fastchess_up():
        say("waiting for previous fastchess")
        time.sleep(20)

    # LMP 8/12/18/24 already held Fruit 22.5%/20g in keepgoing; do not revert it.
    q8 = BASE / "nets" / "enn4_mix25_quiet8m.bin"
    qh = BASE / "nets" / "enn4_mix25_quiet_h25.bin"
    if q8.exists():
        fruit_then_crafty(q8, "quiet8m", fruit_bar=0.18)
    if qh.exists():
        fruit_then_crafty(qh, "quiet_h25", fruit_bar=0.18)
    fruit_then_crafty(BASE / "nets" / "enn4_mix25_wdl20.bin", "mix25wdl")
    qtac = BASE / "nets" / "enn4_mix25_qtac.bin"
    qtac25 = BASE / "nets" / "enn4_mix25_qtac_h25.bin"
    if qtac.exists():
        fruit_then_crafty(qtac, "qtac", fruit_bar=0.18)
    if qtac25.exists():
        fruit_then_crafty(qtac25, "qtac_h25", fruit_bar=0.18)
    for tname, tpath in (
        ("qtac_h20", BASE / "nets" / "enn4_mix25_qtac_h20.bin"),
        ("qtac_h30", BASE / "nets" / "enn4_mix25_qtac_h30.bin"),
        ("qtac_h22", BASE / "nets" / "enn4_mix25_qtac_h22.bin"),
        ("qtac_h28", BASE / "nets" / "enn4_mix25_qtac_h28.bin"),
    ):
        if tpath.exists():
            fruit_then_crafty(tpath, tname, fruit_bar=0.18)
    q3 = BASE / "nets" / "enn4_mix25_qtac3x.bin"
    q3h = BASE / "nets" / "enn4_mix25_qtac3x_h25.bin"
    if q3.exists():
        fruit_then_crafty(q3, "qtac3x", fruit_bar=0.18)
    if q3h.exists():
        fruit_then_crafty(q3h, "qtac3x_h25", fruit_bar=0.18)
    heads = BASE / "nets" / "enn4_mix25_heads.bin"
    w256 = BASE / "nets" / "enn4_w256_qtac3x.bin"
    if heads.exists():
        fruit_then_crafty(heads, "heads", fruit_bar=0.18)
    if w256.exists():
        fruit_then_crafty(w256, "w256qtac", fruit_bar=0.18)

    # qtac_h25 20g Fruit 25% did not hold: 12.5%/24g confirmation. Skip 40g Crafty.

    # milder NMP reduction
    search_canary(
        "nmpr1",
        "        r = 2 + depth // 5\n        r += 1 if depth > 7",
        "        r = 1 + depth // 5\n        r += 1 if depth > 7",
    )
    search_canary(
        "norazor",
        "      if !in_check && depth <= 2 && ply > 0 && static_eval + 200 * depth <= a &&\n         a.abs < Eval::MATE_IN_MAX\n        razor = qsearch(pos, a, a + 1, ply, limits, 0)\n        return razor if razor <= a\n      end",
        "      # razoring off (wait_next canary)\n",
    )

    say("wait_next queue empty — poll cluster; rematch mix25 only if a canary held")
    while True:
        if cluster_up():
            say("llama ssh is open — stop so an agent can use the cluster")
            break
        time.sleep(60)
    say("wait_next exit")


if __name__ == "__main__":
    main()
