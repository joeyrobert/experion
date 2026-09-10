#!/usr/bin/env python3
"""Cross-check the Crystal engine's NNUE eval against a direct read of the
exported "ENN3" bin file, using the exact integer pipeline the engine uses
(not the training-time float model) so this catches format/quantization bugs
that a float-vs-float comparison would miss.

Usage: python3 tools/nnue_check.py nnue.bin "<fen>" [<fen> ...]
Prints the int cp eval for each FEN. Compare against:
  echo -e "position fen <fen>\\neval\\nquit" | EXPERION_BLEND=100 bin/experion
"""
import struct
import sys

PIECE_CHAR = "PNBRQKpnbrqk"
FEATURES_PER_BUCKET = 1536


def king_bucket(sq):
    return 0 if (sq & 7) < 4 else 1


def load_bin(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"ENN4":
        width, = struct.unpack_from('<I', data, 4)
        count = 768 * (width + 1)
        assert len(data) == 8 + 2 * (count + 3 * width)
        return dict(version=4, h=width + 1, hid=0, kb=1, wh_shift=0, w2_shift=0,
                    w1=struct.unpack_from(f'<{count}h', data, 8),
                    bias=struct.unpack_from(f'<{width}h', data, 8 + 2 * count),
                    w2=struct.unpack_from(f'<{2 * width}h', data, 8 + 2 * (count + width)))
    assert data[0:4] == b"ENN3", f"bad magic {data[0:4]!r}"
    h, hid, wh_shift, w2_shift, kb = struct.unpack_from("<iiiii", data, 4)
    off = 24
    w1_rows = FEATURES_PER_BUCKET * kb
    w1 = struct.unpack_from(f"<{w1_rows * h}h", data, off)
    off += w1_rows * h * 2
    wh = struct.unpack_from(f"<{h * hid}h", data, off)
    off += h * hid * 2
    bh = struct.unpack_from(f"<{hid}h", data, off)
    off += hid * 2
    w2 = struct.unpack_from(f"<{2 * hid}h", data, off)
    off += 2 * hid * 2
    assert off == len(data), f"trailing bytes: {len(data) - off}"
    return dict(h=h, hid=hid, wh_shift=wh_shift, w2_shift=w2_shift, kb=kb,
                w1=w1, wh=wh, bh=bh, w2=w2)


def fen_features(fen, kb):
    board = fen.split()[0]
    sq = 56
    wk_sq, bk_sq = 4, 60
    for c in board:
        if c == '/':
            sq -= 16
        elif c.isdigit():
            sq += int(c)
        else:
            if c == 'K':
                wk_sq = sq
            elif c == 'k':
                bk_sq = sq
            sq += 1
    wbucket = king_bucket(wk_sq) if kb > 1 else 0
    bbucket = king_bucket(bk_sq) if kb > 1 else 0

    sq = 56
    w, b = [], []
    phase = 0
    for c in board:
        if c == '/':
            sq -= 16
        elif c.isdigit():
            sq += int(c)
        else:
            pc = PIECE_CHAR.index(c)
            pt = pc % 6
            white = pc < 6
            if pt in (1, 2):
                phase += 1
            elif pt == 3:
                phase += 2
            elif pt == 4:
                phase += 4
            s_w = sq if white else sq ^ 56
            s_b = sq ^ 56 if white else sq
            w.append(wbucket * FEATURES_PER_BUCKET + (0 if white else 1) * 768 + pt * 64 + s_w)
            b.append(bbucket * FEATURES_PER_BUCKET + (1 if white else 0) * 768 + pt * 64 + s_b)
            sq += 1
    stm_white = fen.split()[1] == 'w'
    return w, b, min(phase, 24), stm_white


def evaluate(net, fen):
    if net.get('version') == 4:
        return evaluate_v4(net, fen)
    w, b, phase, stm_white = fen_features(fen, net["kb"])
    h = net["h"]
    hid = net["hid"]
    w1 = net["w1"]

    acc_w = [0] * h
    acc_b = [0] * h
    for fi in w:
        base = fi * h
        for j in range(h):
            acc_w[j] += w1[base + j]
    for fi in b:
        base = fi * h
        for j in range(h):
            acc_b[j] += w1[base + j]

    a = [max(-512, min(512, acc_w[j] + acc_b[j])) for j in range(h)]

    wh = net["wh"]
    bh = net["bh"]
    hidden = [0] * hid
    for j in range(hid):
        acc = bh[j]
        for k in range(h):
            acc += a[k] * wh[k * hid + j]
        v = acc >> net["wh_shift"]
        hidden[j] = max(0, min(512, v))

    w2 = net["w2"]
    out_mg = sum(hidden[j] * w2[j] for j in range(hid)) >> net["w2_shift"]
    out_eg = sum(hidden[j] * w2[hid + j] for j in range(hid)) >> net["w2_shift"]

    ph = max(0, min(24, phase))
    blended = (out_mg * ph + out_eg * (24 - ph)) // 24
    cp = (blended * 600) >> 9
    return cp if stm_white else -cp


def evaluate_v4(net, fen):
    # Independent board parser and scalar integer inference, no trainer imports.
    width = net['h'] - 1
    accum = [[0] * (width + 1) for _ in range(2)]
    phase = 0
    sq = 56
    for c in fen.split()[0]:
        if c == '/':
            sq -= 16
        elif c.isdigit():
            sq += int(c)
        else:
            pc = PIECE_CHAR.index(c)
            color, pt = divmod(pc, 6)
            phase += [0, 1, 1, 2, 4, 0][pt]
            for pov in range(2):
                feature = (color ^ pov) * 384 + pt * 64 + (sq ^ (56 if pov else 0))
                offset = feature * (width + 1)
                for i in range(width + 1):
                    accum[pov][i] += net['w1'][offset + i]
            sq += 1
    diff = [max(0, min(255, accum[0][i] + net['bias'][i]))
            - max(0, min(255, accum[1][i] + net['bias'][i])) for i in range(width)]
    mg = sum(diff[i] * net['w2'][i] for i in range(width))
    eg = sum(diff[i] * net['w2'][width + i] for i in range(width))
    ph = min(24, phase)
    cp = (mg * ph + eg * (24 - ph)) // (24 * 255 * 64) + (accum[0][width] - accum[1][width]) // 16
    cp = max(-28000, min(28000, cp))
    return (cp if fen.split()[1] == 'w' else -cp) + 12


if __name__ == "__main__":
    net = load_bin(sys.argv[1])
    print(f"H={net['h']} HID={net['hid']} KING_BUCKETS={net['kb']} "
          f"wh_shift={net['wh_shift']} w2_shift={net['w2_shift']}", file=sys.stderr)
    for fen in sys.argv[2:]:
        print(f"{evaluate(net, fen)}\t{fen}")
