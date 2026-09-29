#!/usr/bin/env python3
"""ENN5 trainer: king-bucketed (mirrored) 768xKB -> H, stm-relative SCReLU,
output buckets by piece count. Data lives on the GPU as 32-byte packed boards.

Feature index (per perspective c, 0 white / 1 black):
  rel_sq   = sq ^ (56 if c else 0), then ^7 when the own king's rel file >= 4
  bucket   = KBMAP[rank*4 + file] of the mirrored own-king rel square
  idx      = bucket*768 + (piece_color ^ c)*384 + ptype*64 + rel_sq
MUST match src/experion/nnue.cr (ENN5 path).
"""
import argparse
import json
import os
import struct
import time
from pathlib import Path

import numpy as np
import torch

QA, QB = 255, 64
# 4 files (a-d) x 8 ranks, index rank*4+file
KBMAP = [0, 1, 2, 3,
         4, 4, 5, 5,
         6, 6, 6, 6,
         6, 6, 6, 6,
         7, 7, 7, 7,
         7, 7, 7, 7,
         7, 7, 7, 7,
         7, 7, 7, 7]
KB = 8
OB = 8


class Net(torch.nn.Module):
    def __init__(self, h):
        super().__init__()
        self.h = h
        self.ft = torch.nn.Embedding(768 * KB + 1, h, padding_idx=768 * KB)
        torch.nn.init.normal_(self.ft.weight, std=0.02)
        with torch.no_grad():
            self.ft.weight[768 * KB].zero_()
        self.bias = torch.nn.Parameter(torch.zeros(h))
        self.out_w = torch.nn.Parameter(torch.randn(OB, 2 * h) * (1.0 / (2 * h) ** 0.5) * 0.5)
        self.out_b = torch.nn.Parameter(torch.zeros(OB))
        self.register_buffer('kbmap', torch.tensor(KBMAP, dtype=torch.long))

    def perspective_idx(self, code, c):
        # code: [B,64] long piece codes (12 empty); c: [B] long perspective color
        B = code.shape[0]
        dev = code.device
        sqs = torch.arange(64, device=dev)
        flip = (c * 56).unsqueeze(1)  # [B,1]
        is_k = code == (5 + 6 * c).unsqueeze(1)
        ksq = is_k.float().argmax(1)  # [B]
        rk = ksq ^ (c * 56)
        mirror = ((rk & 7) >= 4).long() * 7  # [B]
        rk = rk ^ mirror
        bucket = self.kbmap[(rk >> 3) * 4 + (rk & 7)]  # [B]
        rel_sq = (sqs.unsqueeze(0) ^ flip) ^ mirror.unsqueeze(1)
        pcol = code // 6
        pt = code % 6
        idx = bucket.unsqueeze(1) * 768 + ((pcol ^ c.unsqueeze(1)) * 384) + pt * 64 + rel_sq
        return torch.where(code == 12, torch.full_like(idx, 768 * KB), idx)

    def forward(self, code, stm):
        idx_w = self.perspective_idx(code, torch.zeros_like(stm))
        idx_b = self.perspective_idx(code, torch.ones_like(stm))
        aw = torch.nn.functional.embedding_bag(idx_w, self.ft.weight, mode='sum', padding_idx=768 * KB) + self.bias
        ab = torch.nn.functional.embedding_bag(idx_b, self.ft.weight, mode='sum', padding_idx=768 * KB) + self.bias
        s = stm.unsqueeze(1).bool()
        us = torch.where(s, ab, aw)
        them = torch.where(s, aw, ab)
        x = torch.cat((us, them), 1).clamp(0, 1).square()
        npc = (code != 12).sum(1)
        ob = ((npc - 2) // 4).clamp(0, OB - 1)
        w = self.out_w[ob]
        return (x * w).sum(1) + self.out_b[ob]

    def export(self, path):
        def q(t, s, lo=-32768, hi=32767):
            a = np.rint(t.detach().cpu().numpy().astype(np.float64) * s)
            if a.max() > hi or a.min() < lo:
                raise ValueError('weight out of int range')
            return a
        ft = q(self.ft.weight[:768 * KB], QA).astype('<i2')
        bias = q(self.bias, QA).astype('<i2')
        ow = q(self.out_w, QB).astype('<i2')
        ob = q(self.out_b, QA * QA * QB, -2**31, 2**31 - 1).astype('<i4')
        with open(path, 'wb') as f:
            f.write(b'ENN5' + struct.pack('<IIII', self.h, KB, OB, 0))
            f.write(ft.tobytes())
            f.write(bias.tobytes())
            f.write(ow.tobytes())
            f.write(ob.tobytes())


def unpack(packed):
    # packed: [B,32] uint8 -> [B,64] long
    lo = (packed & 15).long()
    hi = (packed >> 4).long()
    return torch.stack((lo, hi), 2).reshape(packed.shape[0], 64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data')
    ap.add_argument('out')
    ap.add_argument('--h', type=int, default=512)
    ap.add_argument('--epochs', type=int, default=12)
    ap.add_argument('--batch', type=int, default=16384)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--lr-final', type=float, default=1e-5)
    ap.add_argument('--lam', type=float, default=0.25, help='weight on game result in target')
    ap.add_argument('--scale', type=float, default=400.0)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--device', default='cuda:0')
    ap.add_argument('--resume', default='')
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    rank = int(os.environ.get('RANK', 0))
    world = int(os.environ.get('WORLD_SIZE', 1))
    ddp = world > 1
    if ddp:
        torch.distributed.init_process_group('nccl')
        torch.cuda.set_device(int(os.environ['LOCAL_RANK']))
        a.device = f"cuda:{os.environ['LOCAL_RANK']}"
        torch.manual_seed(a.seed + rank)
    dev = a.device
    main_rank = rank == 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'config.json').write_text(json.dumps(vars(a)))
    d = Path(a.data)

    def load(name):
        board = np.load(d / f'{name}_board.npy', mmap_mode='r')
        cp = np.load(d / f'{name}_cp.npy')
        fl = np.load(d / f'{name}_flags.npy')
        n = len(cp) if not (a.limit and name == 'train') else min(len(cp), a.limit)
        lo, hi = 0, n
        if name == 'train' and ddp:
            lo, hi = n * rank // world, n * (rank + 1) // world
        chunks = []
        for i in range(lo, hi, 4_000_000):
            chunks.append(torch.from_numpy(np.ascontiguousarray(board[i:min(hi, i + 4_000_000)])).to(dev))
        return (torch.cat(chunks), torch.from_numpy(cp[lo:hi]).to(dev), torch.from_numpy(fl[lo:hi]).to(dev))

    tr = load('train')
    va = load('val')
    N = len(tr[1])
    if main_rank: print(json.dumps({'train': N, 'val': len(va[1])}), flush=True)
    net = Net(a.h).to(dev)
    if a.resume:
        net.load_state_dict(torch.load(a.resume, map_location=dev))
    model = net
    if ddp:
        model = torch.nn.parallel.DistributedDataParallel(net, device_ids=[int(os.environ['LOCAL_RANK'])])
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=0.0)
    steps_per_epoch = N // a.batch
    if ddp:
        t = torch.tensor([steps_per_epoch], device=dev)
        torch.distributed.all_reduce(t, op=torch.distributed.ReduceOp.MIN)
        steps_per_epoch = int(t.item())
    total_steps = steps_per_epoch * a.epochs
    step = 0

    def lr_at(s):
        t = s / max(1, total_steps)
        return a.lr_final + (a.lr - a.lr_final) * 0.5 * (1 + np.cos(np.pi * t))

    def batch(data, ix):
        code = unpack(data[0][ix])
        fl = data[2][ix].long()
        stm = fl & 1
        res = ((fl >> 1) & 3).float() / 2  # white-POV result 0/.5/1
        cp = data[1][ix].float()
        sign = 1 - 2 * stm.float()
        tgt_cp = cp * sign
        tgt_res = torch.where(stm == 1, 1 - res, res)
        target = (1 - a.lam) * torch.sigmoid(tgt_cp / a.scale) + a.lam * tgt_res
        return code, stm, target

    def evaluate():
        net.eval()
        tot = 0.0
        n = 0
        with torch.no_grad():
            for ix in torch.arange(len(va[1]), device=dev).split(65536):
                code, stm, target = batch(va, ix)
                pred = torch.sigmoid(net(code, stm))
                tot += (pred - target).square().sum().item()
                n += len(ix)
        net.train()
        return tot / n

    best = 1e9
    for epoch in range(1, a.epochs + 1):
        t0 = time.time()
        perm = torch.randperm(N, device=dev)
        run = 0.0
        for bi in range(steps_per_epoch):
            ix = perm[bi * a.batch:(bi + 1) * a.batch]
            code, stm, target = batch(tr, ix)
            for g in opt.param_groups:
                g['lr'] = lr_at(step)
            pred = torch.sigmoid(model(code, stm))
            loss = (pred - target).square().mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            with torch.no_grad():
                net.out_w.clamp_(-500, 500)
                net.ft.weight.clamp_(-120, 120)
            step += 1
            run += loss.item() if bi % 50 == 0 else 0
            if bi % 2000 == 0 and main_rank:
                print(json.dumps({'epoch': epoch, 'step': bi, 'of': steps_per_epoch, 'loss': loss.item(),
                                  'sec': round(time.time() - t0)}), flush=True)
        if not main_rank:
            continue
        vl = evaluate()
        net.export(out / f'epoch-{epoch:03d}.bin')
        torch.save(net.state_dict(), out / f'epoch-{epoch:03d}.pt')
        if vl < best:
            best = vl
            net.export(out / 'best.bin')
        print(json.dumps({'epoch': epoch, 'val_loss': vl, 'sec': round(time.time() - t0)}), flush=True)


if __name__ == '__main__':
    main()
