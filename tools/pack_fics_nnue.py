#!/usr/bin/env python3
"""Pack quiet FICS positions and label eval with an ENN4 checkpoint.

No Crafty labels. Game result is WDL; search-score target comes from the
float ENN4 (same Net as train_nnue_v4.py).
"""
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import sys
from pathlib import Path

import chess
import chess.pgn
import chess.variant
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_nnue_v4 import Net  # noqa: E402

_orig_find_variant = chess.variant.find_variant


def _find_variant(name):
    try:
        return _orig_find_variant(name)
    except ValueError:
        return chess.Board


chess.variant.find_variant = _find_variant

SKIP_VARIANTS = (
    "crazyhouse", "suicide", "losers", "atomic", "chess960", "fischerandom",
    "wildcastle", "3check", "threecheck", "kingofthehill", "horde",
    "racingkings", "giveaway", "bughouse",
)


def features(board):
    white, black = [], []
    phase = 0
    for sq, piece in board.piece_map().items():
        pt = piece.piece_type - 1
        white.append((0 if piece.color else 384) + pt * 64 + sq)
        black.append((384 if piece.color else 0) + pt * 64 + (sq ^ 56))
        phase += [0, 1, 1, 2, 4, 0][pt]
    return white, black, min(phase, 24)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pgn_bz2")
    p.add_argument("out")
    p.add_argument("--pt", required=True, help="ENN4 state_dict to label eval")
    p.add_argument("--width", type=int, default=192)
    p.add_argument("--positions", type=int, default=1_500_000)
    p.add_argument("--device", default="cpu")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n_max = args.positions
    store = {
        split: {
            "w": np.full((n_max, 32), 768, dtype=np.int16),
            "b": np.full((n_max, 32), 768, dtype=np.int16),
            "t": np.empty((n_max, 3), dtype=np.float32),
            "n": 0,
        }
        for split in ("train", "val")
    }
    seen = set()
    games = 0
    kept = 0
    opener = bz2.open if args.pgn_bz2.endswith(".bz2") else open
    with opener(args.pgn_bz2, "rt", errors="replace") as f:
        while kept < n_max:
            try:
                game = chess.pgn.read_game(f)
            except Exception:
                continue
            if game is None:
                break
            games += 1
            variant = game.headers.get("Variant", "").strip().lower().replace(" ", "")
            if variant.startswith("wild") or any(s in variant for s in SKIP_VARIANTS):
                continue
            result = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(
                game.headers.get("Result")
            )
            if result is None:
                continue
            key = "|".join(game.headers.get(k, "") for k in
                           ["Event", "Date", "Round", "White", "Black"])
            split = "val" if int.from_bytes(
                hashlib.blake2b(key.encode(), digest_size=8).digest(), "little"
            ) % 20 == 0 else "train"
            try:
                board = game.board()
            except Exception:
                continue
            try:
                for ply, node in enumerate(game.mainline()):
                    if kept >= n_max:
                        break
                    if ply >= 12 and ply <= 80 and ply % 4 == 0 and not board.is_check():
                        mv = node.move
                        tactical = board.is_capture(mv) or bool(mv.promotion)
                        if not tactical:
                            fen = board.fen()
                            digest = hashlib.blake2b(
                                " ".join(fen.split()[:4]).encode(), digest_size=12
                            ).digest()
                            if digest not in seen:
                                seen.add(digest)
                                w, b, ph = features(board)
                                if len(w) <= 32:
                                    row = store[split]
                                    i = row["n"]
                                    if i < n_max:
                                        row["w"][i, :len(w)] = w
                                        row["b"][i, :len(b)] = b
                                        row["t"][i] = ph, 0.0, result
                                        row["n"] = i + 1
                                        kept += 1
                    board.push(node.move)
            except Exception:
                continue
            if games % 2000 == 0:
                print(games, {k: v["n"] for k, v in store.items()}, flush=True)
    net = Net(args.width).to(args.device)
    pt = Path(args.pt)
    if pt.read_bytes()[:4] == b"ENN4":
        net.load_enn4(str(pt))
    else:
        net.load_state_dict(torch.load(args.pt, map_location=args.device, weights_only=True))
    net.eval()
    with torch.no_grad():
        for split, row in store.items():
            n = row["n"]
            for start in range(0, n, 4096):
                end = min(start + 4096, n)
                w = torch.from_numpy(row["w"][start:end]).to(dtype=torch.long, device=args.device)
                b = torch.from_numpy(row["b"][start:end]).to(dtype=torch.long, device=args.device)
                ph = torch.from_numpy(row["t"][start:end, 0]).to(device=args.device)
                ev = net(w, b, ph).cpu().numpy()
                row["t"][start:end, 1] = ev
    for split, row in store.items():
        n = row["n"]
        np.save(out / f"{split}_w.npy", row["w"][:n])
        np.save(out / f"{split}_b.npy", row["b"][:n])
        np.save(out / f"{split}_targets.npy", row["t"][:n])
    manifest = {
        "source": args.pgn_bz2,
        "games_read": games,
        "positions": {k: v["n"] for k, v in store.items()},
        "kept": kept,
        "label_pt": args.pt,
        "width": args.width,
        "sampling": "FICS quiets ply 12-80 step 4, WDL=game, eval=ENN4",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(manifest, flush=True)


if __name__ == "__main__":
    main()
