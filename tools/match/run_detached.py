#!/usr/bin/env python3
"""Run a ladder match in a new session, detached from the caller.

Cursor aborts agent terminal process groups when a chat is compacted or a
background shell is cancelled. Matches started with this launcher keep
running: new session, nohup-style stdio to a log, caffeinate to block idle
sleep.

Usage:
  python3 tools/match/run_detached.py 10+0.1 10 sungorus [log_stem]

Monitor:
  tail -f tools/match/<log_stem>.log
  cat tools/match/<log_stem>.pid
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
MATCH = BASE / "tools" / "match"


def main() -> None:
    tc = sys.argv[1] if len(sys.argv) > 1 else "10+0.1"
    rounds = sys.argv[2] if len(sys.argv) > 2 else "10"
    opp = sys.argv[3] if len(sys.argv) > 3 else "sungorus"
    stem = sys.argv[4] if len(sys.argv) > 4 else "sungorus_current"

    log_path = MATCH / f"{stem}.log"
    pid_path = MATCH / f"{stem}.pid"
    runner = MATCH / "run_match.sh"

    env = os.environ.copy()
    env.setdefault("CONC", "1")
    env.setdefault("THREADS", "4")
    nnue = env.get("EXPERION_NNUE", "")

    log = open(log_path, "w", buffering=1)
    header = (
        f"=== {opp} {tc} detached {time.strftime('%Y-%m-%d %H:%M:%S')}"
        f" nnue={nnue or 'off'} blend={env.get('EXPERION_BLEND', '')} ===\n"
    )
    log.write(header)
    log.flush()

    # caffeinate -i: do not idle-sleep while the match runs.
    # start_new_session: new process group, not killed with the agent shell.
    proc = subprocess.Popen(
        ["caffeinate", "-i", "zsh", str(runner), tc, rounds, opp],
        cwd=str(BASE),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.write_text(str(proc.pid) + "\n")
    print(f"detached pid={proc.pid} pgid={os.getpgid(proc.pid)} log={log_path}")


if __name__ == "__main__":
    main()
