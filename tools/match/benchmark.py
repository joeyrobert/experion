#!/usr/bin/env python3
"""Reproducible sequential ladder benchmark; isolated PGNs and manifests.

Do not run two timed benchmarks at once on the same hardware. Ratings of
these opponents in other tournaments are not ratings of this engine here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import chess.pgn

BASE = Path(__file__).resolve().parents[2]
MATCH = BASE / 'tools/match'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--net')
    p.add_argument('--blend', type=int, default=100)
    p.add_argument('--threads', type=int, default=1)
    p.add_argument('--tc', default='2+0.02')
    p.add_argument('--rounds', type=int, default=20)
    p.add_argument('--opponents', nargs='+', default=['vice', 'sungorus', 'bbc', 'fruit', 'crafty'])
    args = p.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine = Path(args.engine).resolve()
    env = dict(os.environ)
    env.pop('EXPERION_NNUE', None)
    env.pop('EXPERION_BLEND', None)
    if args.net:
        env['EXPERION_NNUE'] = str(Path(args.net).resolve())
    handshake = subprocess.run([str(engine)], input='uci\nquit\n', text=True,
                               capture_output=True, env=env, timeout=10, check=True).stdout
    if 'uciok' not in handshake or 'option name EvalBlend ' not in handshake:
        raise RuntimeError('Engine did not declare the required UCI options')
    if args.net and 'option name Use NNUE type check default true' not in handshake:
        raise RuntimeError('Requested NNUE failed to load')
    manifest = dict(vars(args), engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                    net_sha256=hashlib.sha256(Path(args.net).read_bytes()).hexdigest() if args.net else None,
                    opening_sha256=hashlib.sha256((MATCH / 'openings.pgn').read_bytes()).hexdigest(),
                    started=time.time(), concurrency=1)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    opponents = {
        'vice': [f'cmd={MATCH}/ladder/vice11'],
        'sungorus': [f'cmd={MATCH}/ladder/sungorus14'],
        'bbc': [f'cmd={MATCH}/ladder/bbc12'],
        'fruit': ['cmd=/Users/joey/Repos/engines/fruit/src/fruit'],
        'crafty': [f'cmd={MATCH}/uci_bridge', f'args=--needs-restart {MATCH}/Crafty-Chess-25.2/crafty252'],
    }
    summary = {}
    for opponent in args.opponents:
        game_path = out / (opponent + '.pgn')
        command = [str(MATCH / 'fastchess-mac-arm64/fastchess'),
                   '-engine', f'cmd={engine}', 'name=Candidate', f'option.Threads={args.threads}',
                   'option.Hash=64', f'option.EvalBlend={args.blend}',
                   '-engine', *opponents.get(opponent, [f'cmd={Path(opponent).resolve()}']), f'name={opponent}',
                   '-each', f'tc={args.tc}', '-rounds', str(args.rounds), '-games', '2', '-repeat',
                   '-openings', f'file={MATCH}/openings.pgn', 'format=pgn', 'order=sequential',
                   '-concurrency', '1', '-pgnout', f'file={game_path}', '-output', 'format=cutechess']
        log = out / (opponent + '.log')
        with log.open('w') as f:
            subprocess.run(command, cwd=out, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)
        scores = []
        with game_path.open() as f:
            while (game := chess.pgn.read_game(f)) is not None:
                result = {'1-0': 1., '0-1': 0., '1/2-1/2': .5}.get(game.headers['Result'])
                if result is None:
                    raise RuntimeError('Unfinished game')
                scores.append(result if game.headers['White'] == 'Candidate' else 1 - result)
        if len(scores) != 2 * args.rounds:
            raise RuntimeError(f'Incomplete match: {len(scores)} games')
        # Paired openings are the unit of sampling for uncertainty.
        pairs = [(scores[i] + scores[i + 1]) / 2 for i in range(0, len(scores), 2)]
        mean = sum(pairs) / len(pairs)
        se = (sum((x - mean) ** 2 for x in pairs) / (len(pairs) * (len(pairs) - 1))) ** .5 if len(pairs) > 1 else 1.
        summary[opponent] = dict(wins=scores.count(1.), draws=scores.count(.5), losses=scores.count(0.),
                                 games=len(scores), score=mean, paired_standard_error=se,
                                 abnormal_termination=('disconnect' in log.read_text().lower() or 'stall' in log.read_text().lower()))
        (out / 'summary.json').write_text(json.dumps(summary, indent=2))
        print(opponent, summary[opponent], flush=True)


if __name__ == '__main__':
    main()
