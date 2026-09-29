#!/usr/bin/env python3
"""After skip-1.5e9 CCRL pack: freeze-linear mix25, 25%/15% blends, Fruit."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
sys.path.insert(0, str(BASE / "tools" / "match"))
import wait_sp as W

DATA = BASE / "datasets" / "ccrl_qtac_skip15e8"
PIDP = BASE / "tools" / "match" / "pack_qtac_skip15e8.pid"
LOGP = BASE / "tools" / "match" / "pack_qtac_skip15e8.out"
MIX25 = W.MIX25


def main() -> None:
    W.say("wait_skip15 start — pack skip 1.5e9, FT, blend, Fruit")
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < 4 * 3600:
        if (DATA / "train_w.npy").exists() and (DATA / "manifest.json").exists():
            W.say("skip15 pack ready")
            break
        if PIDP.exists():
            pid = PIDP.read_text().strip()
            alive = subprocess.run(["ps", "-p", pid], stdout=subprocess.DEVNULL).returncode == 0
            if not alive and not (DATA / "train_w.npy").exists():
                W.say("skip15 pack died")
                if LOGP.exists():
                    W.say(LOGP.read_text()[-800:])
                sys.exit(1)
        now = time.time()
        if now - last >= 120:
            tail = ""
            if LOGP.exists():
                lines = LOGP.read_text(errors="replace").splitlines()
                tail = lines[-1] if lines else ""
            W.say(f"skip15 packing {tail[:120]}")
            last = now
        time.sleep(20)
    else:
        W.say("skip15 pack timeout")
        sys.exit(1)

    nets = W.train_from_npy(DATA, "mix25_skip15")
    W.match_nets(nets)
    W.say("wait_skip15 done — poll cluster")
    while True:
        if W.cluster_up():
            W.say("llama ssh is open")
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
