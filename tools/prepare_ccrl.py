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
    p.add_argument('--skip-bytes', type=int, default=0,
                   help='seek into the PGN so later CCRL games are used')
    p.add_argument('--min-depth', type=int, default=10,
                   help='keep annotations only at this search depth or deeper')
    p.add_argument('--include-tactics', action='store_true',
                   help='keep annotated captures and checks, not only quiets')
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n_max = args.positions
    store = {
        split: {
            'w': np.full((n_max, 32), 768, dtype=np.int16),
            'b': np.full((n_max, 32), 768, dtype=np.int16),
            't': np.empty((n_max, 3), dtype=np.float32),
            'n': 0,
        }
        for split in ('train', 'val')
    }
    seen = set()
    games = 0
    kept = 0
    pat = re.compile(r'(?<![\w.])([+-]?\d+\.\d+)\s*/\s*(\d+)')
    with open(args.pgn, errors='replace') as f, open(out / 'validation.fen', 'w') as vf:
        if args.skip_bytes > 0:
            f.seek(args.skip_bytes)
            f.readline()
        while kept < n_max:
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
                keep = False
                if m and ply >= 8 and int(m[2]) >= args.min_depth and abs(float(m[1])) <= 25:
                    tactical = (board.is_check() or board.is_capture(node.move)
                                or bool(node.move.promotion))
                    keep = args.include_tactics or not tactical
                if keep:
                    fen = board.fen()
                    digest = hashlib.blake2b(' '.join(fen.split()[:4]).encode(), digest_size=12).digest()
                    if digest not in seen:
                        seen.add(digest)
                        w, b, ph = features(board)
                        if len(w) <= 32:
                            row = store[split]
                            i = row['n']
                            if i < n_max:
                                row['w'][i, :len(w)] = w
                                row['b'][i, :len(b)] = b
                                row['t'][i] = ph, float(m[1]) * 100, result
                                row['n'] = i + 1
                                kept += 1
                                if split == 'val':
                                    vf.write(f'{fen};{result};{float(m[1]) * 100}\n')
                board.push(node.move)
                if kept >= n_max:
                    break
            if games % 1000 == 0:
                print(games, {k: v['n'] for k, v in store.items()},
                      'tactics' if args.include_tactics else 'quiet', flush=True)
    for split, row in store.items():
        n = row['n']
        np.save(out / f'{split}_w.npy', row['w'][:n])
        np.save(out / f'{split}_b.npy', row['b'][:n])
        np.save(out / f'{split}_targets.npy', row['t'][:n])
    manifest = {
        'source': args.pgn,
        'games_read': games,
        'positions': {k: v['n'] for k, v in store.items()},
        'kept': kept,
        'score_pov': 'white',
        'position': 'before annotated move',
        'sampling': (f'annotated ply>=8 depth>={args.min_depth} |score|<=25'
                     + (', quiets+captures+checks' if args.include_tactics else ', quiets only')),
        'include_tactics': args.include_tactics,
        'min_depth': args.min_depth,
        'skip_bytes': args.skip_bytes,
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(manifest, flush=True)


if __name__ == '__main__':
    main()
