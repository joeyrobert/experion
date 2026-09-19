#!/usr/bin/env python3
"""Pack Experion vs Fruit match PGNs into fen;wdl;white_cp lines.

Eval comments are the searching engine's STM score. Convert to White cp.
Skip book moves and Fruit's empty {/0 ...} comments.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import chess
import chess.pgn

SCORE_RE = re.compile(r"([+-]?(?:M\d+|\d+\.\d+))/\d+")
FRUIT = "Fruit21_CCRL2694"
OURS = "Experion"


def white_cp(stm_white: bool, comment: str) -> int | None:
    if "book" in comment.lower():
        return None
    m = SCORE_RE.search(comment)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith(("+M", "-M", "M")):
        mate = int(raw.replace("M", "").replace("+", ""))
        cp = 10000 if not raw.startswith("-") else -10000
        if mate == 0:
            return None
    else:
        cp = int(round(float(raw) * 100))
    if abs(cp) > 8000:
        return None
    return cp if stm_white else -cp


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pgn")
    p.add_argument("out")
    args = p.parse_args()
    out = Path(args.out)
    tmp = out.with_suffix(out.suffix + ".tmp")
    games = kept = skipped = 0
    with open(args.pgn, errors="replace") as inf, open(tmp, "w") as ouf:
        while True:
            try:
                game = chess.pgn.read_game(inf)
            except Exception:
                continue
            if game is None:
                break
            h = game.headers
            names = {h.get("White", ""), h.get("Black", "")}
            if FRUIT not in names or OURS not in names:
                continue
            result = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(h.get("Result"))
            if result is None:
                continue
            games += 1
            try:
                board = game.board()
            except Exception:
                continue
            try:
                for ply, node in enumerate(game.mainline()):
                    if 8 <= ply <= 140:
                        cp = white_cp(board.turn == chess.WHITE, node.comment or "")
                        if cp is None:
                            skipped += 1
                        else:
                            fen = board.fen()
                            parts = fen.split()
                            ouf.write(f"{parts[0]} {parts[1]} {parts[2]} {parts[3]};{result};{cp}\n")
                            kept += 1
                    board.push(node.move)
            except Exception:
                continue
            if games % 50 == 0:
                print(f"games={games} kept={kept} skipped={skipped}", flush=True)
    tmp.replace(out)
    print({"games": games, "kept": kept, "skipped": skipped, "out": str(out)}, flush=True)


if __name__ == "__main__":
    main()
