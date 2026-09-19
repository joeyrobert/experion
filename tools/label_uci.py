#!/usr/bin/env python3
"""Relabel fen;wdl;cp lines with an external UCI engine's STM search score.

Keeps the original WDL. Converts engine STM cp to White cp.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SCORE_RE = re.compile(r"score (?:cp (-?\d+)|mate (-?\d+))")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("txt")
    p.add_argument("out")
    p.add_argument("--engine", required=True)
    p.add_argument("--depth", type=int, default=6)
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--hash", type=int, default=64)
    p.add_argument("--limit", type=int, default=0, help="max positions (0=all)")
    p.add_argument("--skip", type=int, default=0)
    args = p.parse_args()

    proc = subprocess.Popen(
        [args.engine],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    assert proc.stdin and proc.stdout

    def send(line: str) -> None:
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

    def wait_for(token: str) -> list[str]:
        lines = []
        while True:
            ln = proc.stdout.readline()
            if not ln:
                raise RuntimeError(f"engine died waiting for {token}")
            ln = ln.strip()
            lines.append(ln)
            if ln == token or ln.startswith(token + " "):
                return lines

    send("uci")
    wait_for("uciok")
    send(f"setoption name Threads value {args.threads}")
    send(f"setoption name Hash value {args.hash}")
    send("setoption name Ponder value false")
    send("isready")
    wait_for("readyok")

    kept = skipped = 0
    with open(args.txt, errors="replace") as inf, open(args.out, "w") as ouf:
        for i, line in enumerate(inf):
            if i < args.skip:
                continue
            if args.limit and kept >= args.limit:
                break
            line = line.strip()
            if ";" not in line:
                skipped += 1
                continue
            parts = line.split(";")
            if len(parts) < 2:
                skipped += 1
                continue
            fen, wdl = parts[0], parts[1]
            stm = fen.split()[1] if " " in fen else "w"
            try:
                send("position fen " + fen)
                send(f"go depth {args.depth}")
                info = wait_for("bestmove")
            except RuntimeError:
                skipped += 1
                break
            stm_cp = None
            for ln in info:
                m = SCORE_RE.search(ln)
                if not m:
                    continue
                if m.group(1) is not None:
                    stm_cp = int(m.group(1))
                else:
                    mate = int(m.group(2))
                    stm_cp = 10000 if mate > 0 else -10000
            if stm_cp is None or abs(stm_cp) > 8000:
                skipped += 1
                continue
            white_cp = stm_cp if stm == "w" else -stm_cp
            ouf.write(f"{fen};{wdl};{white_cp}\n")
            kept += 1
            if kept % 500 == 0:
                print(f"labeled {kept} skipped {skipped}", flush=True)
    send("quit")
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    print({"kept": kept, "skipped": skipped, "out": args.out}, flush=True)


if __name__ == "__main__":
    main()
