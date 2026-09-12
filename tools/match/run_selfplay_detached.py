#!/usr/bin/env python3
"""Run gendata-selfplay in a new session (survives Cursor terminal abort)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")


def main() -> None:
    games = sys.argv[1] if len(sys.argv) > 1 else "8000"
    depth = sys.argv[2] if len(sys.argv) > 2 else "8"
    out = sys.argv[3] if len(sys.argv) > 3 else str(BASE / "datasets" / "selfplay.txt")
    threads = sys.argv[4] if len(sys.argv) > 4 else "4"
    stem = sys.argv[5] if len(sys.argv) > 5 else "selfplay"

    log_path = BASE / "tools" / "match" / f"{stem}.log"
    pid_path = BASE / "tools" / "match" / f"{stem}.pid"
    bin_path = BASE / "bin" / "experion"
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if env.get("EXPERION_SELFPLAY_NNUE") != "1":
        env.pop("EXPERION_NNUE", None)
        env.pop("EXPERION_BLEND", None)

    log = open(log_path, "w", buffering=1)
    nnue = env.get("EXPERION_NNUE", "off")
    log.write(
        f"=== gendata-selfplay {games} d{depth} {out} t{threads} "
        f"nnue={nnue} openings={env.get('EXPERION_OPENINGS', 'off')} "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
    )
    log.flush()

    proc = subprocess.Popen(
        ["caffeinate", "-i", str(bin_path), "gendata-selfplay", games, depth, out, threads],
        cwd=str(BASE),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.write_text(str(proc.pid) + "\n")
    print(f"detached pid={proc.pid} log={log_path} out={out}")


if __name__ == "__main__":
    main()
