#!/usr/bin/env python3
# NNUE trainer for Experion.
#
#   python3 tools/nnue_train.py data.txt [epochs] [out] [init=checkpoint.state]
#
# Architecture (mirrors src/experion/nnue.cr EXACTLY):
#   features : 2 x 768 HalfKA (piece-color-square per perspective)
#   acc      : int32[256] per perspective, sum of w1[feature]  (w1 fixed-point Q1=1024)
#   act      : clamp(acc_w[i] + acc_b[i], 0, 512)
#   out_c    : sum_i act[i] * w2[c][i] >> 20
#   eval cp  : blend(out_mg, out_eg) * 600 >> 10
#
# Data format: "FEN;result;score_cp" (score optional). When scores are present
# the loss is pure regression toward them; otherwise WDL sigmoid vs result.

import sys
import numpy as np
import torch

PIECE_CHAR = "PNBRQKpnbrqk"
H = 256          # overridden by H= arg
Q1 = 1024
OUT_SHIFT = 20


def fen_features(fen):
    board = fen.split()[0]
    sq = 56
    w = []
    b = []
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
            w.append((0 if white else 1) * 768 + pt * 64 + s_w)
            b.append((1 if white else 0) * 768 + pt * 64 + s_b)
            sq += 1
    return w, b, min(phase, 24)


def load_data(path, limit=3000000, maxn=34):
    fens, results, scores = [], [], []
    with open(path) as f:
        for line in f:
            if ';' not in line:
                continue
            parts = line.strip().split(';')
            fen = parts[0]
            # result can be a float (0/0.5/1) or a PGN result string
            raw_res = parts[1] if len(parts) > 1 else "0.5"
            if raw_res == "1-0":
                res = 1.0
            elif raw_res == "0-1":
                res = 0.0
            elif raw_res == "1/2-1/2":
                res = 0.5
            else:
                try:
                    res = float(raw_res)
                except ValueError:
                    res = 0.5
            try:
                sc = float(parts[2]) if len(parts) > 2 else None
            except ValueError:
                sc = None
            fens.append(fen)
            results.append(res)
            scores.append(sc if sc is not None else 0.0)
            if len(fens) >= limit:
                break

    has_scores = any(s != 0.0 for s in scores)
    B = len(fens)
    wi = np.full((B, maxn), -1, dtype=np.int64)
    bi = np.full((B, maxn), -1, dtype=np.int64)
    ph = np.zeros(B, dtype=np.float32)
    for i, fen in enumerate(fens):
        w, b, p = fen_features(fen)
        wi[i, :len(w)] = w
        bi[i, :len(b)] = b
        ph[i] = p
    cache = {
        "wi": wi, "bi": bi,
        "cwl": np.zeros(B, dtype=np.int64), "cbl": np.zeros(B, dtype=np.int64),
        "ph": ph,
    }
    del fens
    return cache, np.array(results, dtype=np.float32), np.array(scores, dtype=np.float32), has_scores


class Net(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w1 = torch.nn.Parameter(torch.zeros(1536, H))
        self.w2 = torch.nn.Parameter(torch.zeros(2, H))
        torch.nn.init.normal_(self.w1, std=1.0 / 64)
        torch.nn.init.normal_(self.w2, std=1.0 / 64)

    def forward(self, wi, bi, phase):
        wf = wi[wi >= 0]
        bf = bi[bi >= 0]
        rows_w = torch.repeat_interleave(
            torch.arange(wi.shape[0], device=wi.device), (wi >= 0).sum(dim=1))
        rows_b = torch.repeat_interleave(
            torch.arange(bi.shape[0], device=bi.device), (bi >= 0).sum(dim=1))
        wa = torch.zeros(wi.shape[0], H, device=wi.device)
        ba = torch.zeros(bi.shape[0], H, device=bi.device)
        if wf.numel():
            wa.index_add_(0, rows_w, self.w1[wf])
        if bf.numel():
            ba.index_add_(0, rows_b, self.w1[bf])
        # Q_SCALE matches the engine: w1 stored *32, symmetric linear window
        act = torch.clamp((wa + ba) * 32.0, -512.0, 512.0) / 512.0
        out = act @ self.w2.t()
        ph = phase.to(act.dtype) / 24.0
        return out[:, 0] * ph + out[:, 1] * (1.0 - ph)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/training.txt"
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    out = sys.argv[3] if len(sys.argv) > 3 else "src/experion/nnue.bin"
    global H
    init_from = None
    lr = 3e-3
    for a in sys.argv[4:]:
        if a.startswith("init="):
            init_from = a[5:]
        elif a.startswith("lr="):
            lr = float(a[3:])
        elif a.startswith("H="):
            H = int(a[2:])

    torch.set_num_threads(6)
    print("loading...", flush=True)
    cache, results, scores, has_scores = load_data(path)
    n_val = max(1, len(results) // 20)

    def sl(sel):
        return (torch.from_numpy(cache["wi"][sel]).to(device),
                torch.from_numpy(cache["bi"][sel]).to(device),
                torch.from_numpy(cache["ph"][sel]).to(device))

    device = "cpu"
    val_sel = np.arange(0, n_val)
    tr_sel = np.arange(n_val, len(results))
    print(f"{len(tr_sel)} train / {len(val_sel)} val (scores: {has_scores})", flush=True)

    net = Net()
    if init_from:
        net.load_state_dict(torch.load(init_from))
        print(f"initialized from {init_from}")
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.StepLR(opt, step_size=15, gamma=0.4)


    K = 6.0  # sigmoid scaling (cp = ev*600 => /100 => *6)

    def loss_parts(ev, r, sc):
        sig_r = torch.sigmoid(K * ev)
        l_wdl = (sig_r - r) ** 2
        target = torch.clamp(sc / 600.0, -12.0, 12.0)
        l_score = (ev - target) ** 2
        return l_wdl, l_score

    # decide upfront whether we have real game results and real score labels.
    # placeholder 0.5 for every sample means the WDL target is meaningless
    # and would only push the net toward predicting 0. Similarly, all-zero
    # scores mean the score labels are placeholders.
    has_real_results = (np.abs(results - 0.5) > 0.01).any()
    has_real_scores = (np.abs(scores) > 0.01).any()
    if not has_real_results and has_real_scores:
        # classical-style data: real scores, no real results — use score loss
        has_scores = True
    elif has_real_results and not has_real_scores:
        # FICS-style data: real results, no real scores — use WDL loss
        has_scores = False
    elif not has_real_results and not has_real_scores:
        # no signal at all — use WDL loss as a no-op
        has_scores = False

    def loss_of(ev, r, sc):
        l_wdl, l_score = loss_parts(ev, r, sc)
        if has_scores and has_real_results:
            return (l_wdl + l_score).mean()
        if has_scores and not has_real_results:
            # has score labels (e.g. from classical eval) but no real game
            # outcomes — use score loss
            return l_score.mean()
        if has_real_results and not has_scores:
            # has real game results but no score labels — use WDL loss
            return l_wdl.mean()
        # neither: use WDL only
        return l_wdl.mean()

    def eval_set(sel):
        with torch.no_grad():
            wi, bi, ph = sl(sel)
            ev = net(wi, bi, ph)
            r = torch.from_numpy(results[sel]).to(device)
            sc = torch.from_numpy(scores[sel]).to(device)
            return loss_of(ev, r, sc).item()

    best = 1e9
    rng = np.random.RandomState(11)
    bs = 512
    vwi, vbi, vph = sl(val_sel)
    vr = torch.from_numpy(results[val_sel]).to(device)
    vsc = torch.from_numpy(scores[val_sel]).to(device)

    for ep in range(epochs):
        perm = rng.permutation(len(tr_sel))
        tot, nb = 0.0, 0
        for st in range(0, len(tr_sel) - bs + 1, bs):
            sel = tr_sel[perm[st:st + bs]]
            wi = torch.from_numpy(cache["wi"][sel]).to(device)
            bi = torch.from_numpy(cache["bi"][sel]).to(device)
            ph = torch.from_numpy(cache["ph"][sel]).to(device)
            r = torch.from_numpy(results[sel]).to(device)
            sc = torch.from_numpy(scores[sel]).to(device)
            ev = net(wi, bi, ph)
            loss = loss_of(ev, r, sc)
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item()
            nb += 1
        with torch.no_grad():
            ev = net(vwi, vbi, vph)
            vl = loss_of(ev, vr, vsc).item()
        print(f"epoch {ep+1}: lr={opt.param_groups[0]['lr']:.5f} train={tot/max(nb,1):.4f} val={vl:.4f}", flush=True)
        if vl < best:
            best = vl
            torch.save(net.state_dict(), out + ".state")
        sched.step()

    sd = torch.load(out + ".state")
    qw1 = np.clip(np.round(sd["w1"].numpy() * 32), -32768, 32767).astype("<i2")
    qw2 = np.clip(np.round(sd["w2"].numpy() * (1 << OUT_SHIFT)), -32768, 32767).astype("<i2")
    with open(out, "wb") as f:
        f.write(b"ENN1")
        f.write(H.to_bytes(4, "little"))
        f.write(qw1.tobytes())
        f.write(qw2.tobytes())
    print(f"exported {out} (best val {best:.4f})")


if __name__ == "__main__":
    main()
