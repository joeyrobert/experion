#!/usr/bin/env python3
"""Keep packed rows where mix25 is off the CCRL teacher by >= min_err cp.

Hard-example mining: extra CCRL windows trained on ALL positions just
cloned mix25. Training only the mistakes should move the heads.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_nnue_v4 import Net  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("npy")
    p.add_argument("out")
    p.add_argument("--resume", required=True)
    p.add_argument("--min-err", type=float, default=180)
    p.add_argument("--max-abs", type=float, default=800)
    p.add_argument("--cap", type=int, default=800_000)
    p.add_argument("--batch", type=int, default=8192)
    p.add_argument("--device", default="mps")
    p.add_argument("--width", type=int, default=192)
    args = p.parse_args()
    src = Path(args.npy)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    net = Net(args.width).to(args.device)
    net.load_enn4(args.resume)
    net.eval()
    rng = np.random.default_rng(20260918)
    kept = {}
    for split in ("train", "val"):
        w = np.load(src / f"{split}_w.npy", mmap_mode="r")
        b = np.load(src / f"{split}_b.npy", mmap_mode="r")
        t = np.load(src / f"{split}_targets.npy", mmap_mode="r")
        sel_w, sel_b, sel_t = [], [], []
        n = len(w)
        with torch.no_grad():
            for i in range(0, n, args.batch):
                j = min(i + args.batch, n)
                tw = torch.from_numpy(np.array(w[i:j])).to(dtype=torch.long, device=args.device)
                tb = torch.from_numpy(np.array(b[i:j])).to(dtype=torch.long, device=args.device)
                tt = torch.from_numpy(np.array(t[i:j], dtype=np.float32)).to(args.device)
                pred = net(tw, tb, tt[:, 0])
                err = (pred - tt[:, 1]).abs()
                mask = (err >= args.min_err) & (tt[:, 1].abs() <= args.max_abs)
                idx = mask.nonzero(as_tuple=False).squeeze(1).cpu().numpy()
                if idx.size:
                    sel_w.append(np.array(w[i:j][idx]))
                    sel_b.append(np.array(b[i:j][idx]))
                    sel_t.append(np.array(t[i:j][idx]))
        if not sel_w:
            print(json.dumps({"split": split, "kept": 0, "src": n}), flush=True)
            continue
        ww = np.concatenate(sel_w)
        bb = np.concatenate(sel_b)
        tt = np.concatenate(sel_t)
        cap = args.cap if split == "train" else max(args.cap // 20, 20_000)
        if len(ww) > cap:
            ix = rng.choice(len(ww), size=cap, replace=False)
            ww, bb, tt = ww[ix], bb[ix], tt[ix]
        np.save(out / f"{split}_w.npy", ww)
        np.save(out / f"{split}_b.npy", bb)
        np.save(out / f"{split}_targets.npy", tt)
        kept[split] = int(len(ww))
        print(json.dumps({"split": split, "kept": int(len(ww)), "src": n}), flush=True)
    (out / "manifest.json").write_text(json.dumps({
        "source": str(src),
        "resume": args.resume,
        "min_err": args.min_err,
        "max_abs": args.max_abs,
        "positions": kept,
    }, indent=2))
    print(json.dumps({"out": str(out), "positions": kept}), flush=True)


if __name__ == "__main__":
    main()
