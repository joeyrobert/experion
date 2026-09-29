#!/usr/bin/env python3
import os, subprocess, sys, time
from pathlib import Path
BASE = Path("/Users/joey/Repos/experion")
NET = BASE / "nets" / "enn4_tactics_mix15.bin"
LOG = BASE / "tools/match/wait_mix15.log"

def say(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    open(LOG,"a").write(line)
    print(msg, flush=True)

def play(opp, stem, rounds):
    while subprocess.run(["pgrep","-x","fastchess"], stdout=subprocess.DEVNULL).returncode == 0:
        time.sleep(15)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(BASE / "tools/match/experion_nnue.sh")
    env["EXPERION_NNUE"] = str(NET)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(f"{int(rounds)*2}g vs {opp}")
    subprocess.run(["python3", str(BASE/"tools/match/run_detached.py"), "10+0.1", rounds, opp, stem], env=env, cwd=str(BASE), check=True)
    path = BASE / "tools/match" / f"{stem}.log"
    while "Finished match" not in path.read_text(errors="replace"):
        time.sleep(20)
    lines = [ln for ln in path.read_text(errors="replace").splitlines() if "Score of Experion" in ln]
    say(lines[-1] if lines else stem)

say("mix15 Crafty 40g then Fruit 20g")
play("crafty", "mix15_crafty", "20")
play("fruit", "mix15_fruit", "10")
say("mix15 done")
