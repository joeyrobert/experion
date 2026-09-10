#!/usr/bin/env python3
# Legacy ENN3 trainer for reproducing historical experiments only.
# Its summed perspectives can erase piece color. Use train_nnue_v4.py
# for new training; more data cannot repair the ENN3 input collision.
#
#   python3 tools/nnue_train.py data.txt [epochs] [out] [init=checkpoint.state]
#
# Architecture (mirrors src/experion/nnue.cr EXACTLY):
#   features : 2 x 768 x KING_BUCKETS HalfKP-lite (king-bucket, piece-color-
#              square per perspective — see KING_BUCKETS comment below)
#   acc      : int32[H] per perspective, sum of w1[feature]  (w1 fixed-point *32)
#   act      : clamp(acc_w[i] + acc_b[i], -512, 512)                [= 512 * act_float in [-1,1]]
#   hidden   : clamp((act . wh + bh_scaled) >> WH_SHIFT, 0, 512)    [= 512 * hidden_float in [0,1]]
#   out_c    : (hidden . w2[c]) >> OUT_SHIFT                        [= 512 * out_float[c]]
#   eval cp  : blend(out_mg, out_eg) * 600 >> 9                     [cancels the leftover 512x]
#
# A validated-by-experiment addition over the original single-layer net: an
# extra HID-wide hidden layer between the accumulator and the two phase
# output heads measurably reduces validation loss (~2% relative, same data/
# epochs/optimizer) — see tools/nnue_arch_experiment.py.
#
# King-relative feature buckets (KING_BUCKETS, see below) were added after
# an exhaustive session ruled out label quality, label quantity, hidden-
# layer capacity, and training stability as the reason NNUE nets — however
# well they scored on material sanity checks — never beat classical eval
# in real games (STS positional-suite solve rate stuck at ~6-7% vs
# classical's 32%, regardless of data/architecture/training fixes). The
# flat, king-position-agnostic feature set could not represent that a
# piece's positional value depends on king position at all — this is the
# actual architectural fix, not another training-recipe tweak. See
# docs/nnue-session-findings.md for the full chain of evidence.
#
# Exported format bumped to "ENN3" (was "ENN2") for both the hidden-layer
# and the king-bucket changes — older engine builds can't load this.
#
# Quantization notes (get this wrong and the exported net silently breaks —
# it did, for hours, earlier this session): every *_SHIFT here is derived
# from the ACTUAL trained weight magnitudes at export time, never picked
# in the abstract. See `export()`.
#
# Data format: "FEN;result;score_cp" (score optional). When scores are present
# the loss is pure regression toward them; otherwise WDL sigmoid vs result.

import sys
import numpy as np
import torch

PIECE_CHAR = "PNBRQKpnbrqk"
H = 256          # overridden by H= arg
HID = 32         # hidden layer width; overridden by HID= arg. 0 = old 1-layer net
Q1 = 1024
# King-relative feature buckets: a scoped version of real NNUE's HalfKP/
# HalfKAv2 (which use up to 64 king-position buckets). Every prior net this
# session used flat, king-position-agnostic features (piece-type x square
# only) — positional value is highly conditional on king position (a
# knight's value differs a lot between a kingside-castled king and a
# queenside one), and that conditioning is information the old feature set
# could not express at all, regardless of label quality/quantity or hidden-
# layer size (all three were tested and ruled out as the bottleneck this
# session — see docs/nnue-session-findings.md).
#
# First attempt used 4 buckets (file quadrant). Result: total collapse —
# 0/40 vs Vice at pure NNUE, mated every game, despite the Crystal engine's
# int pipeline being verified bit-for-bit correct against this exact float
# model (tools/nnue_check.py). Sanity checks (K+2R, K+3R) went persistently
# wrong-signed from epoch ~19 on even as val loss kept smoothly improving —
# a different, worse failure mode than the flat net's late-epoch erosion.
# Hypothesis: splitting the SAME 13.3M-row dataset 4 ways by king file
# quarters the effective training data per bucket for the same 1536
# per-bucket features, without adding any real data — undertraining, not a
# bug. Dropped to 2 buckets (kingside/queenside) to only halve effective
# data per bucket instead of quartering it, as a cheaper test of that
# hypothesis before considering "get much more data" or "share weights
# across buckets". See docs/nnue-session-findings.md for the full record.
KING_BUCKETS = 2
FEATURES_PER_BUCKET = 1536  # unchanged: 2 (own/opp) x 6 (piece types) x 64 (square)


def king_bucket(sq):
    return 0 if (sq & 7) < 4 else 1  # queenside (a-d) vs kingside (e-h)


def fen_features(fen):
    board = fen.split()[0]
    # pass 1: locate both kings (every feature's bucket depends on the
    # OWN-perspective king position, so this must happen before pass 2)
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
    # white's own-perspective king bucket uses its own (unmirrored) square;
    # black's own-perspective bucket uses its king mirrored, matching the
    # existing s_w/s_b mirroring convention below
    wbucket = king_bucket(wk_sq)
    bbucket = king_bucket(bk_sq ^ 56)

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
            w.append(wbucket * FEATURES_PER_BUCKET + (0 if white else 1) * 768 + pt * 64 + s_w)
            b.append(bbucket * FEATURES_PER_BUCKET + (1 if white else 0) * 768 + pt * 64 + s_b)
            sq += 1
    return w, b, min(phase, 24)


def load_data(path, limit=100_000_000, maxn=34):
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
    """Accumulator -> HID-wide hidden layer (clipped ReLU) -> two phase
    heads. Validated via tools/nnue_arch_experiment.py: ~2% lower val loss
    than a direct accumulator->output net, same data/epochs/optimizer."""
    def __init__(self):
        super().__init__()
        self.w1 = torch.nn.Parameter(torch.zeros(FEATURES_PER_BUCKET * KING_BUCKETS, H))
        self.wh = torch.nn.Parameter(torch.zeros(H, HID))
        self.bh = torch.nn.Parameter(torch.zeros(HID))
        self.w2 = torch.nn.Parameter(torch.zeros(2, HID))
        torch.nn.init.normal_(self.w1, std=1.0 / 64)
        torch.nn.init.normal_(self.wh, std=1.0 / 32)
        torch.nn.init.normal_(self.w2, std=1.0 / 16)

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
        hidden = torch.clamp(act @ self.wh + self.bh, 0.0, 1.0)
        out = hidden @ self.w2.t()
        ph = phase.to(act.dtype) / 24.0
        return out[:, 0] * ph + out[:, 1] * (1.0 - ph)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/training.txt"
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    out = sys.argv[3] if len(sys.argv) > 3 else "src/experion/nnue.bin"
    global H, HID
    init_from = None
    lr = 3e-3
    wd = 0.01
    step_size = 15
    bs = 512
    device_override = None
    for a in sys.argv[4:]:
        if a.startswith("init="):
            init_from = a[5:]
        elif a.startswith("lr="):
            lr = float(a[3:])
        elif a.startswith("H="):
            H = int(a[2:])
        elif a.startswith("HID="):
            HID = int(a[4:])
        elif a.startswith("wd="):
            wd = float(a[3:])
        elif a.startswith("step="):
            step_size = int(a[5:])
        elif a.startswith("bs="):
            bs = int(a[3:])
        elif a == "mps":
            device_override = "mps"
        elif a == "cpu":
            device_override = "cpu"
        elif a == "cuda":
            device_override = "cuda"

    torch.set_num_threads(6)
    print("loading...", flush=True)
    cache, results, scores, has_scores = load_data(path)
    n_val = max(1, len(results) // 20)

    def sl(sel):
        return (torch.from_numpy(cache["wi"][sel]).to(device),
                torch.from_numpy(cache["bi"][sel]).to(device),
                torch.from_numpy(cache["ph"][sel]).to(device))

    if device_override:
        device = device_override
    elif torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"device: {device}", flush=True)
    val_sel = np.arange(0, n_val)
    tr_sel = np.arange(n_val, len(results))
    print(f"{len(tr_sel)} train / {len(val_sel)} val (scores: {has_scores})", flush=True)

    net = Net().to(device)
    if init_from:
        net.load_state_dict(torch.load(init_from, map_location=device))
        print(f"initialized from {init_from}")
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=wd)
    # every run this session showed the same pattern: loss flat at the
    # "predict nothing" baseline for dozens of epochs, then a sudden break
    # exactly at the first StepLR decay — a symptom of the initial LR being
    # too large for this architecture to make stable early progress, not of
    # needing more epochs. A short linear warmup (start at lr/20, ramp to
    # lr over the first few epochs) should let training actually progress
    # from epoch 1 instead of wasting the first decay cycle escaping a bad
    # regime.
    warmup_epochs = max(3, epochs // 20)
    warmup = torch.optim.lr_scheduler.LinearLR(
        opt, start_factor=0.05, end_factor=1.0, total_iters=warmup_epochs)
    decay = torch.optim.lr_scheduler.StepLR(opt, step_size=step_size, gamma=0.4)
    sched = torch.optim.lr_scheduler.SequentialLR(
        opt, schedulers=[warmup, decay], milestones=[warmup_epochs])


    K = 6.0  # sigmoid scaling (cp = ev*600 => /100 => *6)

    def loss_parts(ev, r, sc):
        sig_r = torch.sigmoid(K * ev)
        l_wdl = (sig_r - r) ** 2
        target = torch.clamp(sc / 600.0, -12.0, 12.0)
        l_score = (ev - target) ** 2
        return l_wdl, l_score

    # Per-SAMPLE signal masks, not a dataset-wide decision — mixing sources
    # (e.g. FICS: real result, score=0 placeholder; self-play: result=0.5
    # placeholder, real score) means a single global has_scores/has_results
    # flag makes EVERY row use whichever loss terms are real ANYWHERE in the
    # file. Concretely: with a dataset-wide flag, FICS rows (genuinely no
    # score label) still got score-loss computed against a fake target of 0,
    # quietly pulling every human-game position's eval toward zero and
    # diluting its otherwise-clean WDL signal. Caught this only once mixing
    # FICS with self-play/Crafty-labeled data at scale — worth flagging
    # since every training run this session before this fix had it.
    def loss_of(ev, r, sc):
        l_wdl, l_score = loss_parts(ev, r, sc)
        r_mask = (torch.abs(r - 0.5) > 0.01).to(ev.dtype)
        sc_mask = (torch.abs(sc) > 0.01).to(ev.dtype)
        n_signals = (r_mask + sc_mask).clamp(min=1.0)
        per_sample = (r_mask * l_wdl + sc_mask * l_score) / n_signals
        return per_sample.mean()

    def eval_set(sel):
        with torch.no_grad():
            wi, bi, ph = sl(sel)
            ev = net(wi, bi, ph)
            r = torch.from_numpy(results[sel]).to(device)
            sc = torch.from_numpy(scores[sel]).to(device)
            return loss_of(ev, r, sc).item()

    best = 1e9
    rng = np.random.RandomState(11)

    def eval_val_loss():
        # batched like training — a large val set (millions of positions)
        # evaluated in one shot can OOM the GPU (each sample expands to up
        # to 34 sparse indices before the sum).
        tot_l, tot_n = 0.0, 0
        for st in range(0, len(val_sel), bs):
            sel = val_sel[st:st + bs]
            wi, bi, ph = sl(sel)
            r = torch.from_numpy(results[sel]).to(device)
            sc = torch.from_numpy(scores[sel]).to(device)
            with torch.no_grad():
                ev = net(wi, bi, ph)
                tot_l += loss_of(ev, r, sc).item() * len(sel)
                tot_n += len(sel)
        return tot_l / max(tot_n, 1)

    # Sanity-check positions, evaluated periodically during training (not
    # just post-hoc): validation loss alone never caught the large-dataset
    # degradation found this session — it's dominated by the much more
    # common near-balanced positions, so a collapse specifically in extreme-
    # material representation doesn't move it. This is the only check that
    # did catch it.
    sanity_fens = [
        ("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "K+2R"),
        ("4k3/8/8/8/8/8/8/RRR1K3 w Q - 0 1", "K+3R"),
        ("3qk3/8/8/8/8/8/8/4K3 w - - 0 1", "-Q"),
    ]

    def sanity_str():
        parts = []
        with torch.no_grad():
            for fen, label in sanity_fens:
                w, b, ph_ = fen_features(fen)
                swi = torch.full((1, 34), -1, dtype=torch.long)
                sbi = torch.full((1, 34), -1, dtype=torch.long)
                swi[0, :len(w)] = torch.tensor(w)
                sbi[0, :len(b)] = torch.tensor(b)
                sph = torch.tensor([float(ph_)])
                ev = net(swi.to(device), sbi.to(device), sph.to(device))
                parts.append(f"{label}={ev.item()*600:.0f}")
        return " ".join(parts)

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
        vl = eval_val_loss()
        print(f"epoch {ep+1}: lr={opt.param_groups[0]['lr']:.5f} train={tot/max(nb,1):.4f} val={vl:.4f} sanity[{sanity_str()}]", flush=True)
        if vl < best:
            best = vl
            torch.save(net.state_dict(), out + ".state")
        sched.step()

    sd = torch.load(out + ".state", map_location="cpu")

    def pick_shift(max_abs, headroom=1.5, cap=20):
        # largest S with max_abs * 2^S * headroom <= 32767 — derived from
        # the ACTUAL trained magnitude, never picked in the abstract. The
        # original OUT_SHIFT=20 was picked without this check and silently
        # overflowed int16 by ~70x for hours before being caught.
        if max_abs < 1e-9:
            return cap
        s = int(np.floor(np.log2(32767.0 / (headroom * max_abs))))
        return max(0, min(cap, s))

    qw1 = np.clip(np.round(sd["w1"].numpy() * 32), -32768, 32767).astype("<i2")

    wh = sd["wh"].numpy()
    bh = sd["bh"].numpy()
    w2 = sd["w2"].numpy()
    # bias scales with an EXTRA factor of 512 relative to the weight it
    # accompanies (see header comment) — the shift must satisfy both.
    wh_shift = min(pick_shift(np.abs(wh).max()), pick_shift(np.abs(bh).max() * 512))
    w2_shift = pick_shift(np.abs(w2).max())
    qwh = np.clip(np.round(wh * (1 << wh_shift)), -32768, 32767).astype("<i2")
    qbh = np.clip(np.round(bh * 512 * (1 << wh_shift)), -32768, 32767).astype("<i2")
    qw2 = np.clip(np.round(w2 * (1 << w2_shift)), -32768, 32767).astype("<i2")

    clipped = ((np.abs(np.round(wh * (1 << wh_shift))) > 32767).mean(),
               (np.abs(np.round(bh * 512 * (1 << wh_shift))) > 32767).mean(),
               (np.abs(np.round(w2 * (1 << w2_shift))) > 32767).mean())
    if any(c > 0 for c in clipped):
        print(f"WARNING: quantization clipping occurred (wh/bh/w2 fractions): {clipped}", flush=True)

    with open(out, "wb") as f:
        f.write(b"ENN3")
        f.write(H.to_bytes(4, "little"))
        f.write(HID.to_bytes(4, "little"))
        f.write(wh_shift.to_bytes(4, "little"))
        f.write(w2_shift.to_bytes(4, "little"))
        f.write(KING_BUCKETS.to_bytes(4, "little"))
        f.write(qw1.tobytes())
        f.write(qwh.tobytes())
        f.write(qbh.tobytes())
        f.write(qw2.tobytes())
    print(f"exported {out} (best val {best:.4f}, wh_shift={wh_shift}, w2_shift={w2_shift})")


if __name__ == "__main__":
    main()
