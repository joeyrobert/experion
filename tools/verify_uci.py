#!/usr/bin/env python3
"""Bounded UCI regression checks, including immediate stop before startup."""
import argparse
import os
import queue
import subprocess
import threading
import time

import chess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('engine')
    p.add_argument('--net')
    args = p.parse_args()
    env = dict(os.environ)
    env.pop('EXPERION_NNUE', None)
    if args.net:
        env['EXPERION_NNUE'] = os.path.abspath(args.net)
    proc = subprocess.Popen([args.engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
    lines = queue.Queue()
    def reader():
        for line in proc.stdout:
            lines.put(line.strip())
    threading.Thread(target=reader, daemon=True).start()
    def send(command):
        proc.stdin.write(command + '\n')
        proc.stdin.flush()
    def until(prefix, timeout=5):
        deadline = time.monotonic() + timeout
        collected = []
        while time.monotonic() < deadline:
            line = lines.get(timeout=max(.01, deadline - time.monotonic()))
            collected.append(line)
            if line.startswith(prefix):
                return line, collected
        raise TimeoutError(prefix)
    try:
        send('uci')
        _, handshake = until('uciok')
        assert any('option name EvalBlend ' in l for l in handshake)
        send('isready')
        until('readyok')
        for threads in (1, 4):
            send(f'setoption name Threads value {threads}')
            for _ in range(5):
                send('position startpos\ngo infinite\nstop')
                best, _ = until('bestmove')
                assert chess.Move.from_uci(best.split()[1]) in chess.Board().legal_moves
            send('position startpos\ngo nodes 4096')
            best, _ = until('bestmove')
            assert chess.Move.from_uci(best.split()[1]) in chess.Board().legal_moves
        for option in ('setoption name EvalBlend value 0', 'setoption name EvalBlend value 100',
                       'setoption name Use NNUE value false', 'setoption name Use NNUE value true'):
            send(option + '\nposition startpos\ngo depth 2')
            until('bestmove')
        for fen in ('7k/5K2/6Q1/8/8/8/8/8 b - - 0 1', '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1'):
            send('position fen ' + fen + '\ngo depth 2')
            best, _ = until('bestmove')
            assert best == 'bestmove 0000', best
        send('quit')
        assert proc.wait(timeout=5) == 0
        print('UCI handshake, immediate stop (1/4 threads), nodes, eval options, terminal positions, quit: PASS')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


if __name__ == '__main__':
    main()
