#!/usr/bin/env python3
"""Pack Experion self-play text (fen;wdl;white_cp) into ENN4 npy tensors."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

PHASE = [0, 1, 1, 2, 4, 0]
PT = {c: i for i, c in enumerate("PNBRQK")}


def features(fen: str):
    board, stm = fen.split()[:2]
    white, black = [], []
    phase = 0
    sq = 56
    for ch in board:
        if ch == "/":
            sq -= 16
            continue
        if ch.isdigit():
            sq += int(ch)
            continue
        pt = PT[ch.upper()]
        is_white = ch.isupper()
        white.append((0 if is_white else 384) + pt * 64 + sq)
        black.append((384 if is_white else 0) + pt * 64 + (sq ^ 56))
        phase += PHASE[pt]
        sq += 1
    return white, black, min(phase, 24), stm


def main():
    p = argparse.ArgumentParser()
    p.add_argument("txt")
    p.add_argument("out")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = {"train": [], "val": []}
    seen = set()
    kept = 0
    skipped = 0
    with open(args.txt, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or ";" not in line:
                continue
            parts = line.split(";")
            if len(parts) < 3:
                skipped += 1
                continue
            fen, wdl_s, score_s = parts[0], parts[1], parts[2]
            try:
                wdl = float(wdl_s)
                score = float(score_s)
            except ValueError:
                skipped += 1
                continue
            if abs(score) > 20000:
                skipped += 1
                continue
            key = " ".join(fen.split()[:4]).encode()
            digest = hashlib.blake2b(key, digest_size=12).digest()
            if digest in seen:
                skipped += 1
                continue
            seen.add(digest)
            try:
                w, b, ph, _ = features(fen)
            except (KeyError, ValueError, IndexError):
                skipped += 1
                continue
            if len(w) > 32:
                skipped += 1
                continue
            split = "val" if int.from_bytes(digest[:8], "little") % 20 == 0 else "train"
            rows[split].append((w, b, ph, score, wdl))
            kept += 1
    for split, data in rows.items():
        n = len(data)
        wi = np.full((n, 32), 768, dtype=np.int16)
        bi = wi.copy()
        targets = np.empty((n, 3), dtype=np.float32)
        for i, (w, b, ph, sc, r) in enumerate(data):
            wi[i, : len(w)] = w
            bi[i, : len(b)] = b
            targets[i] = ph, sc, r
        np.save(out / f"{split}_w.npy", wi)
        np.save(out / f"{split}_b.npy", bi)
        np.save(out / f"{split}_targets.npy", targets)
    manifest = {
        "source": args.txt,
        "positions": {k: len(v) for k, v in rows.items()},
        "kept": kept,
        "skipped": skipped,
        "score_pov": "white",
        "labels": "self-play search score + game WDL",
        "split": "position hash, 5% val",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(manifest, flush=True)


if __name__ == "__main__":
    main()
