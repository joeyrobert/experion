#!/usr/bin/env python3
"""Cross-check engine ENN5 inference against the torch model.

usage: check_v5.py [net.pt h] -- exports a net (random if no .pt), then compares
the engine's `nnueeval` (integer path, incl. incremental refresh) to torch.
"""
import random
import subprocess
import sys

import chess
import torch

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import train_v5 as T

h = int(sys.argv[2]) if len(sys.argv) > 2 else 64
net = T.Net(h)
if len(sys.argv) > 1 and sys.argv[1] != 'random':
    net.load_state_dict(torch.load(sys.argv[1], map_location='cpu'))
else:
    torch.manual_seed(3)
    with torch.no_grad():
        net.ft.weight.normal_(0, 0.25)
        net.ft.weight[768 * T.KB].zero_()
        net.bias.normal_(0, 0.1)
        net.out_w.normal_(0, 0.5)
        net.out_b.normal_(0, 0.1)
with torch.no_grad():
    net.ft.weight.copy_(torch.round(net.ft.weight * T.QA) / T.QA)
    net.bias.copy_(torch.round(net.bias * T.QA) / T.QA)
    net.mat.copy_(torch.round(net.mat))
    net.out_w.copy_(torch.round(net.out_w * T.QB) / T.QB)
    net.out_b.copy_(torch.round(net.out_b * T.QA * T.QA * T.QB) / (T.QA * T.QA * T.QB))
net.eval()
net.export('/tmp/check_v5.bin')

PC = {}
for color in (True, False):
    for pt in range(1, 7):
        PC[(pt, color)] = (pt - 1) + (0 if color else 6)

random.seed(5)
fens = []
for _ in range(60):
    b = chess.Board()
    for _ in range(random.randint(4, 120)):
        ms = list(b.legal_moves)
        if not ms or b.is_game_over():
            break
        b.push(random.choice(ms))
    if not b.is_game_over():
        fens.append(b.fen())

eng = subprocess.Popen(['bin/experion'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                       env={'EXPERION_NNUE': '/tmp/check_v5.bin', 'EXPERION_BLEND': '100', 'PATH': '/usr/bin'})
worst = 0
for fen in fens:
    b = chess.Board(fen)
    code = torch.full((1, 64), 12, dtype=torch.long)
    for s, p in b.piece_map().items():
        code[0, s] = PC[(p.piece_type, p.color)]
    stm = torch.tensor([0 if b.turn else 1])
    with torch.no_grad():
        ref = 400 * net(code, stm).item()
    eng.stdin.write(f'position fen {fen}\nnnueeval\n')
    line = ''
    while 'info string nnue' not in line:
        line = eng.stdout.readline()
    got = int(line.split()[-1])
    worst = max(worst, abs(got - ref))
    if abs(got - ref) > 3:
        print('MISMATCH', fen, got, round(ref, 1))
print('positions', len(fens), 'worst abs err (cp)', round(worst, 2))
eng.stdin.write('quit\n')
