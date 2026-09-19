#!/usr/bin/env python3
"""Detach a waiter so Cursor agent-shell teardown cannot kill it."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
MATCH = BASE / "tools" / "match"


def main() -> None:
    script = Path(sys.argv[1]).resolve()
    stem = sys.argv[2] if len(sys.argv) > 2 else script.stem
    log_path = MATCH / f"{stem}.out"
    pid_path = MATCH / f"{stem}.pid"
    log = open(log_path, "a", buffering=1)
    proc = subprocess.Popen(
        ["caffeinate", "-i", "python3", "-u", str(script)],
        cwd=str(BASE),
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
