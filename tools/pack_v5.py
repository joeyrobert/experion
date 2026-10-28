#!/usr/bin/env python3
"""Pack gendata-v5 part files into the train/val npy format train_v5.py expects.

  python3 tools/pack_v5.py datasets/selfplay_v5 datasets/v5_selfplay

Reads every *.bin in the first directory (the 64-byte record format documented
in src/experion/gendata_v5.cr), dedups positions globally by Zobrist hash
(exact: hash covers pieces, stm, castling, ep), and writes the same
{train,val}_{board,cp,flags}.npy arrays as merge_v5.py:

  {train,val}_board.npy  uint8[n,32]  two 4-bit piece codes per byte (12 = empty)
  {train,val}_cp.npy     int16[n]     white-POV search score
  {train,val}_flags.npy  uint8[n]     bit0 stm black, bits1-2 result (0 B, 1 D, 2 W)

Train/val are split by GAME (positions from one self-play game never straddle
the split): a splitmix64 finalizer of the record's game id decides. --val-bps
is the val share in basis points (default 0.2%), capped by --max-val.
"""
import argparse
import glob
import os

import numpy as np

REC_BYTES = 64
REC_DTYPE = np.dtype([
    ("board", "u1", 32),
    ("hash", "<u8"),
    ("stm", "u1"),
    ("result", "u1"),
    ("score", "<i2"),
    ("ply", "<u2"),
    ("depth", "<u2"),
    ("gid", "<u8"),
    ("nodes", "<u4"),
    ("pad", "<u4"),
])
MATE_IN_MAX = 29000  # records with |score| above this are mate scores: drop


def gid_mix(g):
    # splitmix64 finalizer, uint64 wrap arithmetic
    with np.errstate(over="ignore", invalid="ignore"):
        x = (g ^ (g >> 30)).astype(np.uint64) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> 27)).astype(np.uint64) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> 31)


def load_records(rec_dir):
    parts = []
    n_raw = 0
    for path in sorted(glob.glob(os.path.join(rec_dir, "*.bin"))):
        data = open(path, "rb").read()
        keep = (len(data) // REC_BYTES) * REC_BYTES  # drop ragged tail
        if keep == 0:
            continue
        rec = np.frombuffer(data[:keep], dtype=REC_DTYPE)
        parts.append(rec)
        n_raw += len(rec)
        print(f"read {path}: {len(rec)} records", flush=True)
    if not parts:
        raise SystemExit(f"no records found in {rec_dir}")
    return np.concatenate(parts), n_raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--val-bps", type=int, default=200, help="val share in basis points")
    ap.add_argument("--max-val", type=int, default=400_000)
    a = ap.parse_args()

    rec, n_raw = load_records(a.rec_dir)

    bad = (np.abs(rec["score"].astype(np.int32)) > MATE_IN_MAX) | \
          (rec["result"] > 2) | (rec["result"] < 0)
    if bad.any():
        print(f"dropping {int(bad.sum())} invalid records (mate scores / bad result codes)", flush=True)
        rec = rec[~bad]

    _, first = np.unique(rec["hash"], return_index=True)
    keep = np.zeros(len(rec), bool)
    keep[first] = True
    print(f"total {len(rec)} unique {int(keep.sum())} (dropped {int((~keep).sum())} duplicates)", flush=True)
    rec = rec[keep]

    is_val = (gid_mix(rec["gid"]) % 100_000) < a.val_bps
    if is_val.sum() > a.max_val:
        idx = np.random.default_rng(1).choice(np.flatnonzero(is_val), a.max_val, replace=False)
        val_mask = np.zeros(len(rec), bool)
        val_mask[idx] = True
        is_val = val_mask

    os.makedirs(a.out_dir, exist_ok=True)
    for name, mask in (("train", ~is_val), ("val", is_val)):
        r = rec[mask]
        board = r["board"].reshape(len(r), 32)
        cp = r["score"].astype(np.int16)
        flags = (r["stm"].astype(np.uint16) | (r["result"].astype(np.uint16) << 1)).astype(np.uint8)
        if name == "train":
            perm = np.random.default_rng(2).permutation(len(cp))
            board, cp, flags = board[perm], cp[perm], flags[perm]
        np.save(f"{a.out_dir}/{name}_board.npy", board)
        np.save(f"{a.out_dir}/{name}_cp.npy", cp)
        np.save(f"{a.out_dir}/{name}_flags.npy", flags)
        print(name, len(cp), flush=True)
    print(f"packed {n_raw} raw records -> {len(rec)} unique into {a.out_dir}", flush=True)


if __name__ == "__main__":
    main()
