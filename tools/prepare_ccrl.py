#!/usr/bin/env python3
"""Extract quiet positions with explicit White-POV CCRL search labels.

CCRL's numeric {+0.60/16 ...} annotations are White POV and describe
the search BEFORE the annotated move. Split by game, deduplicate board
positions globally, and retain genuine zero scores and drawn results.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import chess
import chess.pgn
import numpy as np


def features(board):
    white, black = [], []
    phase = 0
    for sq, piece in board.piece_map().items():
        pt = piece.piece_type - 1
        white.append((0 if piece.color else 384) + pt * 64 + sq)
        black.append((384 if piece.color else 0) + pt * 64 + (sq ^ 56))
        phase += [0, 1, 1, 2, 4, 0][pt]
    return white, black, min(phase, 24)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('pgn')
    p.add_argument('out')
    p.add_argument('--positions', type=int, default=1_000_000)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = {'train': [], 'val': []}
    seen = set()
    games = 0
    pat = re.compile(r'(?<![\w.])([+-]?\d+\.\d+)\s*/\s*(\d+)')
    with open(args.pgn, errors='replace') as f, open(out / 'validation.fen', 'w') as vf:
        while sum(map(len, rows.values())) < args.positions:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            games += 1
            if game.errors:
                continue
            result = {'1-0': 1., '0-1': 0., '1/2-1/2': .5}.get(game.headers.get('Result'))
            if result is None:
                continue
            key = '|'.join(game.headers.get(k, '') for k in ['Event', 'Date', 'Round', 'White', 'Black'])
            split = 'val' if int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), 'little') % 20 == 0 else 'train'
            board = game.board()
            for ply, node in enumerate(game.mainline()):
                m = pat.search(node.comment)
                if (m and ply >= 12 and ply % 4 == games % 4
                        and int(m[2]) >= 10 and abs(float(m[1])) <= 20
                        and not board.is_check() and not board.is_capture(node.move)
                        and not node.move.promotion):
                    fen = board.fen()
                    digest = hashlib.blake2b(' '.join(fen.split()[:4]).encode(), digest_size=12).digest()
                    if digest not in seen:
                        seen.add(digest)
                        w, b, ph = features(board)
                        rows[split].append((w, b, ph, float(m[1]) * 100, result))
                        if split == 'val':
                            vf.write(f'{fen};{result};{float(m[1]) * 100}\n')
                board.push(node.move)
            if games % 1000 == 0:
                print(games, {k: len(v) for k, v in rows.items()}, flush=True)
    for split, data in rows.items():
        n = len(data)
        wi = np.full((n, 32), 768, dtype=np.int16)
        bi = wi.copy()
        targets = np.empty((n, 3), dtype=np.float32)
        for i, (w, b, ph, sc, r) in enumerate(data):
            wi[i, :len(w)] = w
            bi[i, :len(b)] = b
            targets[i] = ph, sc, r
        np.save(out / (split + '_w.npy'), wi)
        np.save(out / (split + '_b.npy'), bi)
        np.save(out / (split + '_targets.npy'), targets)
    manifest = {'source': args.pgn, 'games_read': games, 'positions': {k: len(v) for k, v in rows.items()},
                'score_pov': 'white', 'position': 'before annotated quiet move', 'split': 'game hash, global position deduplication'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(manifest, flush=True)


if __name__ == '__main__':
    main()
