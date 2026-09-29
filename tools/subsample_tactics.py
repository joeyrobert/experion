#!/usr/bin/env python3
"""Random 2.5M/0.15M subsample of data_tactics so quiets can still dominate a mix."""
import json
from pathlib import Path

import numpy as np

src = Path("/w/data_tactics")
dst = Path("/w/data_tactics3m")
dst.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(20260910)
for split, n_max in (("train", 2_500_000), ("val", 150_000)):
    t = np.load(src / f"{split}_targets.npy", mmap_mode="r")
    n = min(n_max, len(t))
    idx = rng.choice(len(t), size=n, replace=False)
    idx.sort()
    for name in ("w", "b", "targets"):
        arr = np.load(src / f"{split}_{name}.npy", mmap_mode="r")
        np.save(dst / f"{split}_{name}.npy", np.asarray(arr[idx]))
    print(split, n, flush=True)
man = json.loads((src / "manifest.json.real").read_text())
man["subsample"] = {"train": 2_500_000, "val": 150_000, "from": "data_tactics"}
(dst / "manifest.json").write_text(json.dumps(man, indent=2))
print("wrote", dst, flush=True)
