#!/usr/bin/env python3
"""
Extract NNUE training data from a FICS PGN database.

Streams a bz2 PGN, parses games with python-chess, extracts positions
at midgame plies. Filters for "quiet" positions (no capture/check on
the next move, paper 2412.17948 style). Labels each position with the
game result.

Output: FEN;result;0 (one per line)
"""
import sys
import bz2
import random
import chess
import chess.pgn

def is_quiet(board, ply_ahead=2):
    """paper 2412.17948 style: a position is quiet if the next few moves
    are not captures or checks. We check the next 2 plies (one move each)."""
    b = board.copy()
    for _ in range(ply_ahead):
        if b.is_check():
            return False
        moves = list(b.legal_moves)
        # find a non-capture move
        quiet = [m for m in moves if not b.is_capture(m)]
        if not quiet:
            return False
        # play the first quiet move
        b.push(quiet[0])
    return True


def main():
    if len(sys.argv) < 3:
        print("usage: extract_fics.py <pgn.bz2> <out.txt> [target] [min_ply] [max_ply] [sample_rate]")
        sys.exit(1)
    in_path = sys.argv[1]
    out_path = sys.argv[2]
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 100000
    min_ply = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    max_ply = int(sys.argv[5]) if len(sys.argv) > 5 else 120
    sample_rate = float(sys.argv[6]) if len(sys.argv) > 6 else 0.05  # 5% of games

    out = open(out_path, "w")
    emitted = 0
    processed = 0
    skipped = 0
    with bz2.open(in_path, "rt") as f:
        while emitted < target:
            try:
                game = chess.pgn.read_game(f)
            except Exception:
                break
            if game is None:
                break
            processed += 1
            if processed % 10000 == 0:
                print(f"Processed {processed}, emitted {emitted}, skipped {skipped}", file=sys.stderr)

            if random.random() > sample_rate:
                skipped += 1
                continue

            result = game.headers.get("Result", "*")
            if result not in ("1-0", "0-1", "1/2-1/2"):
                continue

            # walk the game
            board = game.board()
            ply = 0
            positions_in_game = 0
            for move in game.mainline_moves():
                board.push(move)
                ply += 1
                # extract at midgame plies
                if ply < min_ply or ply > max_ply:
                    continue
                if ply % 4 != 0:
                    continue
                if board.is_check():
                    continue
                if not is_quiet(board):
                    continue
                # write FEN;result;0
                fen = board.fen()
                out.write(f"{fen};{result};0\n")
                positions_in_game += 1
                emitted += 1
                if positions_in_game >= 20:  # cap per game
                    break
                if emitted >= target:
                    break

    out.close()
    print(f"Processed {processed} games, emitted {emitted} positions", file=sys.stderr)


if __name__ == "__main__":
    main()
