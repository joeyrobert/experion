#!/usr/bin/env python3
"""Dump fen;wdl;white_cp lines from a CCRL commented PGN (White-POV scores)."""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import chess
import chess.pgn

PAT = re.compile(r"(?<![\w.])([+-]?\d+\.\d+)\s*/\s*(\d+)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pgn")
    p.add_argument("out")
    p.add_argument("--positions", type=int, default=200_000)
    p.add_argument("--skip-bytes", type=int, default=0)
    p.add_argument("--min-depth", type=int, default=12)
    p.add_argument("--include-tactics", action="store_true")
    args = p.parse_args()
    out = Path(args.out)
    tmp = out.with_suffix(out.suffix + ".tmp")
    seen = set()
    games = kept = skipped = 0
    with open(args.pgn, errors="replace") as inf, open(tmp, "w") as ouf:
        if args.skip_bytes > 0:
            inf.seek(args.skip_bytes)
            inf.readline()
        while kept < args.positions:
            game = chess.pgn.read_game(inf)
            if game is None:
                break
            games += 1
            result = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(game.headers.get("Result"))
            if result is None:
                continue
            board = game.board()
            try:
                for ply, node in enumerate(game.mainline()):
                    m = PAT.search(node.comment or "")
                    if m and ply >= 8 and int(m[2]) >= args.min_depth and abs(float(m[1])) <= 25:
                        tactical = (board.is_check() or board.is_capture(node.move)
                                    or bool(node.move.promotion))
                        if args.include_tactics or not tactical:
                            fen = board.fen()
                            digest = hashlib.blake2b(
                                " ".join(fen.split()[:4]).encode(), digest_size=12
                            ).digest()
                            if digest not in seen:
                                seen.add(digest)
                                parts = fen.split()
                                cp = int(round(float(m[1]) * 100))
                                ouf.write(f"{parts[0]} {parts[1]} {parts[2]} {parts[3]};{result};{cp}\n")
                                kept += 1
                                if kept >= args.positions:
                                    break
                    board.push(node.move)
            except Exception:
                skipped += 1
            if games % 1000 == 0:
                print(f"games={games} kept={kept}", flush=True)
    tmp.replace(out)
    print({"games": games, "kept": kept, "skipped": skipped, "out": str(out)}, flush=True)


if __name__ == "__main__":
    main()
