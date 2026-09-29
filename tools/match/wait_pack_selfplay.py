#!/usr/bin/env python3
"""Wait for self-play pid, then pack npy. Detached so Cursor cannot stall it."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
PID_PATH = BASE / "tools" / "match" / "selfplay.pid"
TXT = BASE / "datasets" / "selfplay.txt"
NPY = BASE / "datasets" / "selfplay_npy"
LOG = BASE / "tools" / "match" / "selfplay_pack.log"
PACK = BASE / "tools" / "prepare_selfplay.py"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> None:
    log = open(LOG, "w", buffering=1)
    def say(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}\n"
        log.write(line)
        log.flush()
        print(msg, flush=True)

    pid = int(PID_PATH.read_text().strip())
    say(f"waiting for selfplay pid {pid}")
    while alive(pid):
        time.sleep(20)
    say("selfplay process exited")
    if not TXT.exists() or TXT.stat().st_size < 1000:
        say(f"missing or tiny output: {TXT}")
        sys.exit(1)
    say(f"packing {TXT} -> {NPY}")
    r = subprocess.run(["python3", str(PACK), str(TXT), str(NPY)], cwd=str(BASE))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
