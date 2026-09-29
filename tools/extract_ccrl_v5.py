#!/usr/bin/env python3
"""Parallel CCRL extractor for the v5 pipeline.

Emits fixed-width records per byte-range chunk of the commented CCRL PGN:
  pc   uint8[n,32]  piece code 0-5 white PNBRQK, 6-11 black, 255 padding
  sq   uint8[n,32]  square 0-63 (a1=0)
  meta int16[n,5]   stm (0 white/1 black), cp (white POV), result (0/1/2 = B/D/W), ply, is_val
  hash uint64[n]    position hash for global dedup
Quiet filter matches prepare_ccrl.py: annotated, depth>=min-depth, not in
check, played move is not a capture/promotion.
"""
import argparse
import hashlib
import io
import os
import re
from multiprocessing import Pool
from pathlib import Path

import chess
import chess.pgn
import numpy as np

PAT = re.compile(r'(?<![\w.])([+-]?\d+\.\d+)\s*/\s*(\d+)')
PC = {}
for color in (True, False):
    for pt in range(1, 7):
        PC[(pt, color)] = (pt - 1) + (0 if color else 6)


def work(job):
    path, start, end, out, min_depth, cap = job
    outp = Path(out)
    if outp.with_suffix('.done').exists():
        return out, -1
    pcs, sqs, meta, hashes = [], [], [], []
    with open(path, 'rb') as fb:
        fb.seek(start)
        if start > 0:
            # resync to the next game header
            while True:
                pos = fb.tell()
                line = fb.readline()
                if not line or line.startswith(b'[Event '):
                    fb.seek(pos)
                    break
        data = fb.read(max(0, end - fb.tell())) if end else fb.read()
        if end:
            rest = []
            while True:
                line = fb.readline()
                if not line or line.startswith(b'[Event '):
                    break
                rest.append(line)
            data += b''.join(rest)
    f = io.StringIO(data.decode('utf-8', errors='replace'))
    while True:
        try:
            game = chess.pgn.read_game(f)
        except Exception:
            continue
        if game is None:
            break
        if game.errors:
            continue
        result = {'1-0': 2, '0-1': 0, '1/2-1/2': 1}.get(game.headers.get('Result'))
        if result is None:
            continue
        key = '|'.join(game.headers.get(k, '') for k in ['Event', 'Date', 'Round', 'White', 'Black'])
        val = int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), 'little') % 20 == 0
        board = game.board()
        for ply, node in enumerate(game.mainline()):
            m = PAT.search(node.comment)
            if m and ply >= 8 and int(m[2]) >= min_depth and abs(float(m[1])) <= cap:
                if not (board.is_check() or board.is_capture(node.move) or node.move.promotion):
                    pm = board.piece_map()
                    if len(pm) <= 32:
                        pc = np.full(32, 255, np.uint8)
                        sq = np.zeros(32, np.uint8)
                        for i, (s, p) in enumerate(pm.items()):
                            pc[i] = PC[(p.piece_type, p.color)]
                            sq[i] = s
                        fen4 = ' '.join(board.fen().split()[:4])
                        h = int.from_bytes(hashlib.blake2b(fen4.encode(), digest_size=8).digest(), 'little')
                        pcs.append(pc)
                        sqs.append(sq)
                        meta.append((0 if board.turn else 1, int(round(float(m[1]) * 100)), result, ply, int(val)))
                        hashes.append(h)
            board.push(node.move)
    np.savez(outp, pc=np.array(pcs, np.uint8).reshape(-1, 32), sq=np.array(sqs, np.uint8).reshape(-1, 32),
             meta=np.array(meta, np.int16).reshape(-1, 5), hash=np.array(hashes, np.uint64))
    outp.with_suffix('.done').touch()
    return out, len(meta)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pgn')
    ap.add_argument('outdir')
    ap.add_argument('--chunk-mb', type=int, default=64)
    ap.add_argument('--procs', type=int, default=os.cpu_count())
    ap.add_argument('--min-depth', type=int, default=10)
    ap.add_argument('--cap', type=float, default=25)
    ap.add_argument('--limit-chunks', type=int, default=0)
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    size = os.path.getsize(a.pgn)
    step = a.chunk_mb << 20
    jobs = []
    for i, s in enumerate(range(0, size, step)):
        e = min(size, s + step)
        jobs.append((a.pgn, s, e if e < size else 0, str(out / f'chunk{i:04d}.npz'), a.min_depth, a.cap))
    if a.limit_chunks:
        jobs = jobs[:a.limit_chunks]
    total = 0
    with Pool(a.procs) as pool:
        for k, (name, n) in enumerate(pool.imap_unordered(work, jobs)):
            total += max(n, 0)
            print(k + 1, len(jobs), name, n, total, flush=True)


if __name__ == '__main__':
    main()
