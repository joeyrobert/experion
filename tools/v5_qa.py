#!/usr/bin/env python3
"""QA checks for gendata-v5 record files. Stdlib only (no numpy).

  python3 tools/v5_qa.py datasets/selfplay_v5 [--engine bin/experion] [--samples 8]

1. Format contract: for known FENs, the engine's `packboard` output must match
   this script's independent pure-Python packing byte for byte. Catches any
   nibble-order or piece-code drift between the Crystal generator and the
   Python packers (pack_v5.py, merge_v5.py, train_v5.py all use the same
   packed layout).
2. Record sanity on generated data: field ranges (result codes, non-mate
   scores, stm, minimum ply), exactly one king per side, no pawns on rank
   1/8, and a decode of a few sample positions.
3. Label sanity (the docs/TRAINING.md guard): the correlation of the score
   label with material balance and with the game result must be clearly
   positive. Sign/POV mistakes show up here before they cost a training run.
"""
import argparse
import glob
import os
import statistics
import struct

REC_BYTES = 64
REC_FMT = struct.Struct("<32sQBBhHHQII")
MATE_IN_MAX = 29000
PIECE_CHARS = "PNBRQKpnbrqk"  # must equal PIECE_CHAR in src/experion/types.cr
MAT = [100, 320, 330, 500, 900, 0]  # material lane values used by train_v5.py


def pack_board_fen(fen_board: str) -> bytes:
    """Pure-Python packed board for a FEN piece placement string."""
    board = [12] * 64  # a1=0 ordering, 12 = empty
    sq = 56
    for ch in fen_board:
        if ch == "/":
            sq -= 16
        elif ch.isdigit():
            sq += int(ch)
        else:
            code = PIECE_CHARS.index(ch)
            board[sq] = code
            sq += 1
    out = bytearray(32)
    for j in range(32):
        out[j] = (board[2 * j + 1] << 4) | board[2 * j]
    return bytes(out)


def unpack_board(packed: bytes):
    board = [12] * 64
    for j in range(32):
        board[2 * j] = packed[j] & 15
        board[2 * j + 1] = packed[j] >> 4
    return board


def render(board) -> str:
    rows = []
    for rank in range(7, -1, -1):
        row = ""
        empty = 0
        for file in range(8):
            pc = board[rank * 8 + file]
            if pc == 12:
                empty += 1
            else:
                row += (str(empty) if empty else "") + PIECE_CHARS[pc]
                empty = 0
        if empty:
            row += str(empty)
        rows.append(row)
    return "/".join(rows)


def material(board) -> int:
    bal = 0
    for pc in board:
        if pc == 12:
            continue
        bal += MAT[pc % 6] * (1 if pc < 6 else -1)
    return bal


def check_contract(engine: str):
    fen_boards = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",
        "r1bqkbnr/pppppppp/2n5/8/4P3/8/PPPP1PPP/RNBQKBNR",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8",
        "4k3/8/8/8/8/8/8/4K3",
        "8/8/8/8/8/8/6P1/6K1",
        "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR",
    ]
    import subprocess
    ok = True
    for fb in fen_boards:
        expect = pack_board_fen(fb)
        got_hex = subprocess.run([engine, "packboard", fb + " w - - 0 1"],
                                 capture_output=True, text=True).stdout.strip()
        got = bytes.fromhex(got_hex)
        status = "ok" if got == expect else "MISMATCH"
        if got != expect:
            ok = False
        print(f"contract {status}: {fb} expect={expect.hex()} got={got.hex()}")
    return ok


def check_records(rec_dir: str, samples: int):
    paths = sorted(glob.glob(os.path.join(rec_dir, "part_*.bin")))
    if not paths:
        raise SystemExit(f"no part_*.bin records found in {rec_dir}")
    n = bad_field = bad_board = 0
    mats, cpw, results = [], [], []
    shown = 0
    for path in paths:
        with open(path, "rb") as f:
            while True:
                raw = f.read(REC_BYTES)
                if len(raw) < REC_BYTES:
                    break
                board_bytes, h, stm, result, score, ply, depth, gid, nodes, pad = REC_FMT.unpack(raw)
                n += 1
                if result > 2 or stm > 1 or abs(score) > MATE_IN_MAX or ply < 12:
                    bad_field += 1
                board = unpack_board(board_bytes)
                wk = sum(1 for p in board if p == 5)
                bk = sum(1 for p in board if p == 11)
                pawns_bad = any(
                    (board[sq] in (0, 6)) and (sq < 8 or sq >= 56) for sq in range(64)
                )
                if wk != 1 or bk != 1 or pawns_bad:
                    bad_board += 1
                    if shown < 3:
                        shown += 1
                        print(f"BAD BOARD: {render(board)} (wk={wk} bk={bk} pawnrank={pawns_bad})")
                mats.append(material(board))
                cpw.append(score)
                results.append({0: 0.0, 1: 0.5, 2: 1.0}[result])
                if shown < samples and stm == 1 and abs(score) > 150 and nodes > 4000:
                    shown += 1
                    print(f"SAMPLE ply={ply} stm=black score_white={score} matw={material(board)} "
                          f"depth={depth} result={result}\n  {render(board)}")
    if n == 0:
        raise SystemExit("no complete records")
    print(f"records: {n}  field-violations: {bad_field}  board-violations: {bad_board}")
    if len(set(cpw)) > 1 and len(set(mats)) > 1:
        c_mat = statistics.correlation(cpw, mats)
        c_res = statistics.correlation(cpw, results) if len(set(results)) > 1 else float("nan")
        print(f"corr(score, material) = {c_mat:.4f}  (expect strongly positive)")
        print(f"corr(score, result)   = {c_res:.4f}  (expect positive)")
        mean_abs = sum(abs(c) for c in cpw) / n
        wins = sum(1 for r in results if r != 0.5)
        print(f"mean |score| = {mean_abs:.1f} cp, decisive fraction = {wins / n:.3f}")
        return c_mat > 0.5 and c_res > 0.0 and bad_field == 0 and bad_board == 0
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec_dir")
    ap.add_argument("--engine", default="bin/experion")
    ap.add_argument("--samples", type=int, default=8)
    a = ap.parse_args()
    ok_contract = check_contract(a.engine)
    ok_records = check_records(a.rec_dir, a.samples)
    print("CONTRACT", "OK" if ok_contract else "FAIL")
    print("RECORDS", "OK" if ok_records else "FAIL")
    raise SystemExit(0 if (ok_contract and ok_records) else 1)


if __name__ == "__main__":
    main()
