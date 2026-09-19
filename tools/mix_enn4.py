#!/usr/bin/env python3
"""Interpolate two ENN4 bins. Keeps A's linear PSQT column unless --all."""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np


def load(path: Path):
    raw = path.read_bytes()
    if raw[:4] != b"ENN4":
        raise ValueError(f"{path} is not ENN4")
    width, = struct.unpack_from("<I", raw, 4)
    count = 768 * (width + 1)
    w1 = np.frombuffer(raw, dtype="<i2", count=count, offset=8).reshape(768, width + 1).copy()
    bias = np.frombuffer(raw, dtype="<i2", count=width, offset=8 + 2 * count).copy()
    output = np.frombuffer(raw, dtype="<i2", count=2 * width,
                           offset=8 + 2 * (count + width)).copy()
    return width, w1, bias, output


def save(path: Path, width, w1, bias, output) -> None:
    with open(path, "wb") as f:
        f.write(b"ENN4" + struct.pack("<I", width))
        f.write(np.clip(np.rint(w1), -32767, 32767).astype("<i2").tobytes())
        f.write(np.clip(np.rint(bias), -32767, 32767).astype("<i2").tobytes())
        f.write(np.clip(np.rint(output), -32767, 32767).astype("<i2").tobytes())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("base")
    p.add_argument("other")
    p.add_argument("out")
    p.add_argument("--t", type=float, default=0.25, help="weight on other heads")
    p.add_argument("--all", action="store_true", help="also blend the linear column")
    args = p.parse_args()
    wA, a1, ab, ao = load(Path(args.base))
    wB, b1, bb, bo = load(Path(args.other))
    if wA != wB:
        raise SystemExit(f"width mismatch {wA} vs {wB}")
    t = args.t
    w1 = a1.astype(np.float64)
    w1[:, :wA] = (1 - t) * a1[:, :wA] + t * b1[:, :wA]
    if args.all:
        w1[:, wA] = (1 - t) * a1[:, wA] + t * b1[:, wA]
    bias = (1 - t) * ab + t * bb
    output = (1 - t) * ao + t * bo
    save(Path(args.out), wA, w1, bias, output)
    print({"out": args.out, "t": t, "all": args.all}, flush=True)


if __name__ == "__main__":
    main()
