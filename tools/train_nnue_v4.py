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

    def _sum_features(self, idx, weight):
        # embedding_bag is missing on MPS (PyTorch 2.8). B×32×H at batch 4096
        # is ~100MB, cheap enough to materialize on every device.
        if idx.device.type == 'mps':
            return F.embedding(idx, weight, padding_idx=768).sum(1)
        return F.embedding_bag(idx, weight, mode='sum', padding_idx=768)

    def forward(self, w, b, ph):
        wa = self._sum_features(w, self.ft.weight)
        ba = self._sum_features(b, self.ft.weight)
        act = (wa + self.bias).clamp(0, 1) - (ba + self.bias).clamp(0, 1)
        heads = act @ self.output.T
        lin = (self._sum_features(w, self.linear.weight)
               - self._sum_features(b, self.linear.weight)).squeeze(1) / 2
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

    def load_enn4(self, path):
        """Dequantize an exported ENN4 bin so we can fine-tune without a .pt."""
        raw = Path(path).read_bytes()
        if raw[:4] != b'ENN4':
            raise ValueError(f'{path} is not ENN4')
        width, = struct.unpack_from('<I', raw, 4)
        if width != self.width:
            raise ValueError(f'{path} width {width} != net {self.width}')
        count = 768 * (width + 1)
        w1 = np.frombuffer(raw, dtype='<i2', count=count, offset=8).reshape(768, width + 1)
        bias = np.frombuffer(raw, dtype='<i2', count=width, offset=8 + 2 * count)
        output = np.frombuffer(raw, dtype='<i2', count=2 * width,
                               offset=8 + 2 * (count + width)).reshape(2, width)
        with torch.no_grad():
            self.ft.weight[:768].copy_(torch.from_numpy(w1[:, :width].astype(np.float32) / 255))
            self.linear.weight[:768].copy_(torch.from_numpy(w1[:, width:].astype(np.float32) / 8))
            self.bias.copy_(torch.from_numpy(bias.astype(np.float32) / 255))
            self.output.copy_(torch.from_numpy(output.astype(np.float32) / 64))
            self.ft.weight[768].zero_()
            self.linear.weight[768].zero_()


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
    p.add_argument('--resume', default='', help='path to a prior Net state_dict (.pt)')
    p.add_argument('--freeze-linear', action='store_true',
                   help='do not train the material/PSQT linear path')
    p.add_argument('--freeze-ft', action='store_true',
                   help='do not train the 768->H embedding or its bias')
    p.add_argument('--eval-weight', type=float, default=.9,
                   help='weight on search-score MSE (sigmoid cp/400)')
    p.add_argument('--wdl-weight', type=float, default=.1,
                   help='weight on game-result MSE')
    args = p.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(4)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    man_path = Path(args.data) / 'manifest.json'
    metadata = dict(vars(args), torch_version=torch.__version__, numpy_version=np.__version__,
                    python=sys.version, device_name=torch.cuda.get_device_name(args.device) if args.device.startswith('cuda') else args.device,
                    dataset=json.loads(man_path.read_text()) if man_path.exists() else None)
    (out / 'config.json').write_text(json.dumps(metadata, indent=2))
    data = {}
    for split in ('train', 'val'):
        # Keep feature indices as int16 on CPU. Casting 20M rows to int64
        # here used ~10GB and fought the host's 22GB with a packer still up.
        # embedding_bag wants Long; cast per batch on the way to the GPU.
        data[split] = [
            torch.from_numpy(np.load(Path(args.data) / (split + '_' + s + '.npy'))).contiguous()
            for s in ('w', 'b', 'targets')
        ]
    net = Net(args.width).to(args.device)
    # llama is down: the 40M tactics waiter still trains from scratch unless we
    # intercept. Scratch tactics already collapsed material; fine-tune ship w192.
    ship = Path(__file__).resolve().parents[1] / 'nets' / 'enn4_w192all.bin'
    if not args.resume and Path(args.out).name == 'enn4_tactics40m_train' and ship.exists():
        args.resume = str(ship)
        args.lr = min(args.lr, 0.0006)
        args.epochs = min(args.epochs, 8)
        print(json.dumps({'auto_resume': args.resume, 'lr': args.lr, 'epochs': args.epochs}), flush=True)
    if args.resume:
        if Path(args.resume).read_bytes()[:4] == b'ENN4':
            net.load_enn4(args.resume)
        else:
            net.load_state_dict(torch.load(args.resume, map_location=args.device, weights_only=True))
        print(json.dumps({'resume': args.resume}), flush=True)
    if args.freeze_linear:
        net.linear.weight.requires_grad_(False)
        print(json.dumps({'freeze_linear': True}), flush=True)
    if args.freeze_ft:
        net.ft.weight.requires_grad_(False)
        net.bias.requires_grad_(False)
        print(json.dumps({'freeze_ft': True}), flush=True)
    params = [p for p in net.parameters() if p.requires_grad]
    opt = torch.optim.Adam(params, lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs, eta_min=args.lr * .05)
    def loss(ev, target):
        # Search scores are the primary signal, with all actual game results
        # (including draws) retained. No missing-label inference from values.
        pred = torch.sigmoid(ev / 400)
        return (args.eval_weight * (pred - torch.sigmoid(target[:, 1] / 400)).square().mean()
                + args.wdl_weight * (pred - target[:, 2]).square().mean())
    def batch_on_device(split, ix):
        w, b, t = data[split]
        ix = ix.cpu()
        # non_blocking copies to MPS can race and produce NaN losses.
        nb = args.device.startswith('cuda')
        return (w[ix].to(dtype=torch.long, device=args.device, non_blocking=nb),
                b[ix].to(dtype=torch.long, device=args.device, non_blocking=nb),
                t[ix].to(dtype=torch.float32, device=args.device, non_blocking=nb))
    best = float('inf')
    for epoch in range(1, args.epochs + 1):
        start = time.monotonic()
        w, b, t = data['train']
        order = torch.randperm(len(w))
        total = 0.
        net.train()
        for ix in order.split(args.batch):
            bw, bb, bt = batch_on_device('train', ix)
            opt.zero_grad(set_to_none=True)
            err = loss(net(bw, bb, bt[:, 0]), bt)
            if not torch.isfinite(err):
                raise RuntimeError(f'non-finite loss at epoch {epoch}')
            err.backward()
            opt.step()
            total += err.item() * len(ix)
        sched.step()
        net.eval()
        with torch.no_grad():
            vw = data['val'][0]
            vl = 0.
            for ix in torch.arange(len(vw)).split(args.batch):
                bw, bb, bt = batch_on_device('val', ix)
                vl += loss(net(bw, bb, bt[:, 0]), bt).item() * len(ix)
            vl /= len(vw)
        net.export(out / f'epoch-{epoch:03d}.bin')
        if vl < best:
            best = vl
            net.export(out / 'best.bin')
            torch.save(net.state_dict(), out / 'best.pt')
        print(json.dumps({'epoch': epoch, 'train_loss': total / len(w), 'val_loss': vl,
                          'seconds': round(time.monotonic() - start, 2)}), flush=True)


if __name__ == '__main__':
    main()
