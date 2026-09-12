#!/usr/bin/env python3
"""Concatenate ENN4 npy packs. Upsample later dirs so self-play is not drowned."""
import argparse
import json
from pathlib import Path

import numpy as np


def load(dir_path: Path):
    out = {}
    for split in ("train", "val"):
        out[split] = {
            "w": np.load(dir_path / f"{split}_w.npy"),
            "b": np.load(dir_path / f"{split}_b.npy"),
            "targets": np.load(dir_path / f"{split}_targets.npy"),
        }
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dirs", nargs="+", help="npy directories; first is the base set")
    p.add_argument("out")
    p.add_argument("--upsample-rest", type=int, default=3,
                   help="repeat every directory after the first this many times")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    packs = [load(Path(d)) for d in args.dirs]
    rng = np.random.default_rng(20260910)
    manifest = {"sources": args.dirs, "upsample_rest": args.upsample_rest, "positions": {}}
    for split in ("train", "val"):
        parts_w, parts_b, parts_t = [], [], []
        for i, pack in enumerate(packs):
            reps = 1 if i == 0 else max(1, args.upsample_rest)
            for _ in range(reps):
                parts_w.append(pack[split]["w"])
                parts_b.append(pack[split]["b"])
                parts_t.append(pack[split]["targets"])
        w = np.concatenate(parts_w)
        b = np.concatenate(parts_b)
        t = np.concatenate(parts_t)
        order = rng.permutation(len(w))
        np.save(out / f"{split}_w.npy", w[order])
        np.save(out / f"{split}_b.npy", b[order])
        np.save(out / f"{split}_targets.npy", t[order])
        manifest["positions"][split] = int(len(w))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(manifest, flush=True)


if __name__ == "__main__":
    main()
