#!/usr/bin/env python3
"""Merge extract_ccrl_v5 chunks: global dedup, pack boards to 32 bytes/pos.

Outputs (in outdir):
  {train,val}_board.npy  uint8[n,32]  two 4-bit piece codes per byte (12 = empty)
  {train,val}_cp.npy     int16[n]     white-POV search score
  {train,val}_flags.npy  uint8[n]     bit0 stm black, bits1-2 result (0 B, 1 D, 2 W)
"""
import argparse
import glob
import sys

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('chunks')
    ap.add_argument('outdir')
    ap.add_argument('--max-val', type=int, default=400_000)
    a = ap.parse_args()
    import os
    files = [f for f in sorted(glob.glob(a.chunks + '/chunk*.npz')) if os.path.exists(f[:-4] + '.done')]
    hashes = [np.load(f)['hash'] for f in files]
    sizes = [len(h) for h in hashes]
    allh = np.concatenate(hashes)
    del hashes
    _, first = np.unique(allh, return_index=True)
    keep = np.zeros(len(allh), bool)
    keep[first] = True
    del allh, first
    print('total', len(keep), 'unique', int(keep.sum()), flush=True)
    off = 0
    parts = {'train': [], 'val': []}
    for f, n in zip(files, sizes):
        d = np.load(f)
        k = keep[off:off + n]
        off += n
        pc, sq, meta = d['pc'][k], d['sq'][k], d['meta'][k]
        m = len(pc)
        if m == 0:
            continue
        board = np.full((m, 64), 12, np.uint8)
        rows = np.repeat(np.arange(m), 32).reshape(m, 32)
        valid = pc != 255
        board[rows[valid], sq[valid]] = pc[valid]
        packed = (board[:, 0::2] | (board[:, 1::2] << 4)).astype(np.uint8)
        flags = (meta[:, 0] | (meta[:, 2] << 1)).astype(np.uint8)
        cp = meta[:, 1].astype(np.int16)
        isv = meta[:, 4] == 1
        for name, mask in (('train', ~isv), ('val', isv)):
            parts[name].append((packed[mask], cp[mask], flags[mask]))
    import os
    os.makedirs(a.outdir, exist_ok=True)
    for name, lst in parts.items():
        board = np.concatenate([x[0] for x in lst])
        cp = np.concatenate([x[1] for x in lst])
        flags = np.concatenate([x[2] for x in lst])
        if name == 'val' and len(cp) > a.max_val:
            idx = np.random.default_rng(1).choice(len(cp), a.max_val, replace=False)
            board, cp, flags = board[idx], cp[idx], flags[idx]
        elif name == 'train':
            perm = np.random.default_rng(2).permutation(len(cp))
            board, cp, flags = board[perm], cp[perm], flags[perm]
        np.save(f'{a.outdir}/{name}_board.npy', board)
        np.save(f'{a.outdir}/{name}_cp.npy', cp)
        np.save(f'{a.outdir}/{name}_flags.npy', flags)
        print(name, len(cp), flush=True)


if __name__ == '__main__':
    main()
