#!/usr/bin/env python3
"""Serial Crafty samples after wait_book's crafty_book match.

Order: crafty_book (wait_book) → crafty_tactics → crafty_qt.
Does not overlap fastchess. Does not rebuild while gendata-selfplay is alive.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("/Users/joey/Repos/experion")
LOG = BASE / "tools" / "match" / "crafty_seq.log"
WRAPPER = BASE / "tools" / "match" / "experion_nnue.sh"
BOOK_LOG = BASE / "tools" / "match" / "crafty_book.log"
BOOK_PID = BASE / "tools" / "match" / "wait_book_selfplay.pid"
NETS = [
    (BASE / "nets" / "enn4_tactics.bin", "crafty_tactics"),
    (BASE / "nets" / "enn4_qt.bin", "crafty_qt"),
]


def say(log, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    log.write(line)
    log.flush()
    print(msg, flush=True)


def finished(path: Path) -> bool:
    return path.exists() and "Finished match" in path.read_text(errors="replace")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def fastchess_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "fastchess"], stdout=subprocess.DEVNULL)
    return r.returncode == 0


def launch(log, net: Path, stem: str) -> None:
    while fastchess_running():
        time.sleep(10)
    env = os.environ.copy()
    env["EXPERION_BIN"] = str(WRAPPER)
    env["EXPERION_NNUE"] = str(net)
    env["EXPERION_BLEND"] = "100"
    env["CONC"] = "1"
    env["THREADS"] = "4"
    say(log, f"launching 10+0.1 10 rounds {stem} net={net.name}")
    r = subprocess.run(
        ["python3", str(BASE / "tools" / "match" / "run_detached.py"),
         "10+0.1", "10", "crafty", stem],
        cwd=str(BASE), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    if r.returncode != 0:
        say(log, f"failed rc={r.returncode}")
        sys.exit(r.returncode)
    match_log = BASE / "tools" / "match" / f"{stem}.log"
    while not finished(match_log):
        time.sleep(15)
    say(log, match_log.read_text(errors="replace")[-300:])


def main() -> None:
    log = open(LOG, "w", buffering=1)
    say(log, "waiting for crafty_book to finish (or book waiter to die)")
    while True:
        if finished(BOOK_LOG):
            break
        # wait_book detaches the match and exits; the log existing means
        # Crafty is already playing — do not start another sample.
        if BOOK_LOG.exists() and not finished(BOOK_LOG):
            time.sleep(15)
            continue
        if BOOK_PID.exists():
            pid = int(BOOK_PID.read_text().strip() or "0")
            if pid and not alive(pid) and not finished(BOOK_LOG):
                say(log, "book waiter exited without crafty_book; running net samples anyway")
                break
        time.sleep(15)
    for net, stem in NETS:
        if not net.exists():
            say(log, f"skip {stem}: missing {net}")
            continue
        launch(log, net, stem)
    say(log, "sequence done")


if __name__ == "__main__":
    main()
