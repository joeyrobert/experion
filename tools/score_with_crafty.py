#!/usr/bin/env python3
"""
Label a set of FEN positions with Crafty's own eval (classical-only, CCRL
3041) instead of our own ~1700-Elo classical eval. Fixes the circularity
where self-play labels came from a search that could never exceed the
strength of the eval sitting at its own leaf nodes.

Talks to Crafty directly in raw XBoard protocol (the repo's UCI bridge only
supports game-continuation `position startpos moves...`, not arbitrary FEN
scoring — confirmed via /tmp/bridge_traffic.log, "fen position unsupported").

Usage: score_with_crafty.py <in.txt (FEN;result;score)> <out.txt> <seconds_per_move> [worker_id] [n_workers]
"""
import sys
import subprocess
import re
import time

CRAFTY_BIN = "./crafty252"
SCORE_RE = re.compile(r'^\s*\d+\s+(-?\d+)\s+\d+\s+\d+\s')


class Crafty:
    def __init__(self):
        self.p = subprocess.Popen(
            [CRAFTY_BIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
            cwd="tools/match/Crafty-Chess-25.2")
        self._send("xboard")
        self._send("protover 2")
        time.sleep(0.5)
        self._drain()
        self._send("post")

    def _send(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()

    def _drain(self):
        # non-blocking-ish: read whatever's buffered right now via a short
        # readline loop guarded by the "done=1" feature marker
        while True:
            line = self.p.stdout.readline()
            if not line or "feature done=1" in line:
                break

    def score(self, fen, seconds):
        self._send(f"setboard {fen}")
        self._send(f"st {seconds}")
        self._send("go")
        last_score = None
        deadline = time.time() + seconds + 5
        while time.time() < deadline:
            line = self.p.stdout.readline()
            if not line:
                break
            m = SCORE_RE.match(line)
            if m:
                last_score = int(m.group(1))
            if line.startswith("move ") or line.startswith("1-0") or line.startswith("0-1") or line.startswith("1/2"):
                break
        return last_score

    def close(self):
        try:
            self._send("quit")
            self.p.wait(timeout=3)
        except Exception:
            self.p.kill()


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    worker_id = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    n_workers = int(sys.argv[5]) if len(sys.argv) > 5 else 1

    lines = [l for l in open(in_path) if ';' in l]
    my_lines = lines[worker_id::n_workers]

    crafty = Crafty()
    out = open(out_path, "w")
    n = 0
    for line in my_lines:
        parts = line.strip().split(';')
        fen = parts[0]
        result = parts[1] if len(parts) > 1 else "0.5"
        try:
            board_stm = fen.split()[1]  # 'w' or 'b'
        except IndexError:
            continue
        score = crafty.score(fen, seconds)
        if score is None:
            continue
        # Crafty's post output is from the side-to-move's own perspective;
        # convert to white POV to match this project's training convention.
        white_pov = score if board_stm == 'w' else -score
        out.write(f"{fen};{result};{white_pov}\n")
        n += 1
        if n % 500 == 0:
            out.flush()
            print(f"worker {worker_id}: scored {n}/{len(my_lines)}", file=sys.stderr, flush=True)
    crafty.close()
    out.close()
    print(f"worker {worker_id}: done, {n} positions -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
