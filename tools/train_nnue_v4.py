#!/usr/bin/env python3
"""Color-preserving NNUE: shared 768->H clipped ReLU, antisymmetric
phase heads, and a trainable linear piece-square path initialized with
material. ENN4 exports all inference weights; runtime is entirely Crystal.
"""
import argparse
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


class Net(torch.nn.Module):
    def __init__(self, width=256):
        super().__init__()
        self.width = width
        self.ft = torch.nn.Embedding(769, width, padding_idx=768)
        torch.nn.init.normal_(self.ft.weight, std=.015)
        self.bias = torch.nn.Parameter(torch.full((width,), .1))
        self.output = torch.nn.Parameter(torch.randn(2, width))
        self.linear = torch.nn.Embedding(769, 1, padding_idx=768)
        with torch.no_grad():
            for i in range(768):
                self.linear.weight[i] = [100, 320, 330, 500, 900, 0][(i % 384) // 64] * (1 if i < 384 else -1)
            self.ft.weight[768].zero_()
            self.linear.weight[768].zero_()

    def forward(self, w, b, ph):
        # embedding_bag avoids materializing B x 32 x H feature tensors.
        wa = F.embedding_bag(w, self.ft.weight, mode='sum', padding_idx=768)
        ba = F.embedding_bag(b, self.ft.weight, mode='sum', padding_idx=768)
        act = (wa + self.bias).clamp(0, 1) - (ba + self.bias).clamp(0, 1)
        heads = act @ self.output.T
        lin = (F.embedding_bag(w, self.linear.weight, mode='sum', padding_idx=768)
               - F.embedding_bag(b, self.linear.weight, mode='sum', padding_idx=768)).squeeze(1) / 2
        return lin + heads[:, 0] * ph / 24 + heads[:, 1] * (1 - ph / 24)

    def export(self, path):
        def quant(t, scale):
            a = np.rint(t.detach().cpu().numpy() * scale)
            if np.abs(a).max() > 32767:
                raise ValueError('weight cannot be represented as int16')
            return a.astype('<i2')
        # Extra accumulator lane holds linear PSQT scores, quantized at 8.
        w1 = np.concatenate((quant(self.ft.weight[:768], 255), quant(self.linear.weight[:768], 8)), axis=1)
        with open(path, 'wb') as f:
            f.write(b'ENN4' + struct.pack('<I', self.width))
            f.write(w1.tobytes())
            f.write(quant(self.bias, 255).tobytes())
            f.write(quant(self.output, 64).tobytes())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('data')
    p.add_argument('out')
    p.add_argument('--epochs', type=int, default=30)
    p.add_argument('--width', type=int, default=256)
    p.add_argument('--batch', type=int, default=4096)
    p.add_argument('--lr', type=float, default=.003)
    p.add_argument('--seed', type=int, default=20260908)
    p.add_argument('--device', default='cuda:0')
    args = p.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(4)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metadata = dict(vars(args), torch_version=torch.__version__, numpy_version=np.__version__,
                    python=sys.version, device_name=torch.cuda.get_device_name(args.device) if args.device.startswith('cuda') else args.device,
                    dataset=json.loads((Path(args.data) / 'manifest.json').read_text()))
    (out / 'config.json').write_text(json.dumps(metadata, indent=2))
    data = {}
    for split in ('train', 'val'):
        data[split] = [torch.as_tensor(np.load(Path(args.data) / (split + '_' + s + '.npy')), device=args.device,
                                      dtype=torch.long if s in ('w', 'b') else torch.float32) for s in ('w', 'b', 'targets')]
    net = Net(args.width).to(args.device)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs, eta_min=args.lr * .05)
    def loss(ev, target):
        # Search scores are the primary signal, with all actual game results
        # (including draws) retained. No missing-label inference from values.
        pred = torch.sigmoid(ev / 400)
        return .9 * (pred - torch.sigmoid(target[:, 1] / 400)).square().mean() + .1 * (pred - target[:, 2]).square().mean()
    best = float('inf')
    for epoch in range(1, args.epochs + 1):
        start = time.monotonic()
        w, b, t = data['train']
        order = torch.randperm(len(w), device=args.device)
        total = 0.
        net.train()
        for ix in order.split(args.batch):
            opt.zero_grad(set_to_none=True)
            err = loss(net(w[ix], b[ix], t[ix, 0]), t[ix])
            err.backward()
            opt.step()
            total += err.item() * len(ix)
        sched.step()
        net.eval()
        with torch.no_grad():
            vw, vb, vt = data['val']
            vl = sum(loss(net(vw[ix], vb[ix], vt[ix, 0]), vt[ix]).item() * len(ix)
                     for ix in torch.arange(len(vw), device=args.device).split(args.batch)) / len(vw)
        net.export(out / f'epoch-{epoch:03d}.bin')
        if vl < best:
            best = vl
            net.export(out / 'best.bin')
            torch.save(net.state_dict(), out / 'best.pt')
        print(json.dumps({'epoch': epoch, 'train_loss': total / len(w), 'val_loss': vl,
                          'seconds': round(time.monotonic() - start, 2)}), flush=True)


if __name__ == '__main__':
    main()
