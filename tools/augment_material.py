#!/usr/bin/env python3
"""
Generate synthetic material-imbalance positions from a FEN;result;score
dataset. Real quiet-filtered game positions are almost always close to
material balance, so an NNUE net trained only on them never sees examples
that teach it "big material edge -> big score" and collapses toward tiny
output magnitudes even on trivially winning positions.

For each sampled source FEN, strips 0-6 random non-king pieces from one
random side and re-exports the FEN. Output still needs classical-eval
scoring afterward (pipe through `bin/experion score-fics`).

Usage: augment_material.py <in.txt> <out.txt> <count>
"""
import sys
import random
import chess


def main():
    in_path, out_path, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
    lines = [l for l in open(in_path) if ';' in l]
    rng = random.Random(42)
    out = open(out_path, "w")
    emitted = 0
    attempts = 0
    while emitted < count and attempts < count * 4:
        attempts += 1
        line = rng.choice(lines)
        fen = line.split(';')[0]
        try:
            board = chess.Board(fen)
        except Exception:
            continue
        side = rng.choice([chess.WHITE, chess.BLACK])
        n_strip = rng.randint(0, 6)
        candidates = [
            sq for sq, pc in board.piece_map().items()
            if pc.color == side and pc.piece_type != chess.KING
        ]
        rng.shuffle(candidates)
        for sq in candidates[:n_strip]:
            board.remove_piece_at(sq)
        # skip degenerate boards (e.g. stripped down to bare kings + stalemate)
        if board.is_valid() is False:
            continue
        out.write(f"{board.fen()};0.5;0\n")
        emitted += 1
    out.close()
    print(f"generated {emitted} synthetic FENs -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
