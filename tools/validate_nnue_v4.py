#!/usr/bin/env python3
"""Measure float/export error on held-out positions, plus material sanity."""
import argparse
import json
from pathlib import Path

import chess
import numpy as np
import torch

from nnue_check import evaluate, load_bin
from prepare_ccrl import features
from train_nnue_v4 import Net


def main():
    p = argparse.ArgumentParser()
    p.add_argument('run')
    p.add_argument('validation')
    p.add_argument('--limit', type=int, default=300)
    a = p.parse_args()
    run = Path(a.run)
    config = json.loads((run / 'config.json').read_text())
    model = Net(config['width'])
    model.load_state_dict(torch.load(run / 'best.pt', map_location='cpu', weights_only=True))
    model.eval()
    binary = load_bin(run / 'best.bin')
    fens = []
    with open(a.validation) as f:
        for line in f:
            fens.append(line.split(';')[0])
            if len(fens) == a.limit:
                break
    w = np.full((len(fens), 32), 768, dtype=np.int64)
    b = w.copy()
    ph = []
    for i, fen in enumerate(fens):
        wi, bi, phase = features(chess.Board(fen))
        w[i, :len(wi)] = wi
        b[i, :len(bi)] = bi
        ph.append(phase)
    with torch.no_grad():
        floating = model(torch.from_numpy(w), torch.from_numpy(b), torch.tensor(ph)).numpy()
    integer = np.array([(evaluate(binary, fen) - 12) * (1 if fen.split()[1] == 'w' else -1) for fen in fens])
    error = integer - floating
    sanity = {fen: evaluate(binary, fen) for fen in [
        chess.STARTING_FEN,
        '4k3/8/8/8/8/8/R7/4K3 w - - 0 1',
        '4k3/8/8/8/8/8/r7/4K3 w - - 0 1',
        '4k3/8/8/8/8/8/RR6/4K3 w - - 0 1',
        '4k3/8/8/8/8/8/q7/4K3 w - - 0 1']}
    result = dict(positions=len(fens), float_export_mae_cp=float(np.abs(error).mean()),
                  float_export_max_error_cp=float(np.abs(error).max()), sanity_cp=sanity)
    print(json.dumps(result, indent=2))
    assert np.abs(error).max() < 15, result
    assert list(sanity.values())[1] > 250 and list(sanity.values())[2] < -250, result


if __name__ == '__main__':
    main()
