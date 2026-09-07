#!/usr/bin/env python3
# One-off experiment: does adding a hidden layer after the accumulator
# actually reduce validation loss vs the current 1-layer architecture,
# on the same data/epochs/optimizer? Answers the architecture-vs-data-scale
# question in pure Python (no engine-side quantization risk) before
# committing to the harder integer-inference implementation.
import sys
sys.path.insert(0, '.')
import nnue_train as nt
import torch
import numpy as np

path = sys.argv[1]
epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 60
H = 512
HID = 32
nt.H = H
device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
print(f"device: {device}", flush=True)


class Net1(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w1 = torch.nn.Parameter(torch.zeros(1536, H))
        self.w2 = torch.nn.Parameter(torch.zeros(2, H))
        torch.nn.init.normal_(self.w1, std=1.0 / 64)
        torch.nn.init.normal_(self.w2, std=1.0 / 64)

    def forward(self, wi, bi, phase):
        wf = wi[wi >= 0]
        bf = bi[bi >= 0]
        rows_w = torch.repeat_interleave(torch.arange(wi.shape[0], device=wi.device), (wi >= 0).sum(dim=1))
        rows_b = torch.repeat_interleave(torch.arange(bi.shape[0], device=bi.device), (bi >= 0).sum(dim=1))
        wa = torch.zeros(wi.shape[0], H, device=wi.device)
        ba = torch.zeros(bi.shape[0], H, device=bi.device)
        if wf.numel():
            wa.index_add_(0, rows_w, self.w1[wf])
        if bf.numel():
            ba.index_add_(0, rows_b, self.w1[bf])
        act = torch.clamp((wa + ba) * 32.0, -512.0, 512.0) / 512.0
        out = act @ self.w2.t()
        ph = phase.to(act.dtype) / 24.0
        return out[:, 0] * ph + out[:, 1] * (1.0 - ph)


class Net2(torch.nn.Module):
    """Same accumulator, one extra hidden layer (clipped ReLU) before the
    phase heads — closer to real NNUE architectures."""
    def __init__(self):
        super().__init__()
        self.w1 = torch.nn.Parameter(torch.zeros(1536, H))
        self.wh = torch.nn.Parameter(torch.zeros(H, HID))
        self.bh = torch.nn.Parameter(torch.zeros(HID))
        self.w2 = torch.nn.Parameter(torch.zeros(2, HID))
        torch.nn.init.normal_(self.w1, std=1.0 / 64)
        torch.nn.init.normal_(self.wh, std=1.0 / 32)
        torch.nn.init.normal_(self.w2, std=1.0 / 16)

    def forward(self, wi, bi, phase):
        wf = wi[wi >= 0]
        bf = bi[bi >= 0]
        rows_w = torch.repeat_interleave(torch.arange(wi.shape[0], device=wi.device), (wi >= 0).sum(dim=1))
        rows_b = torch.repeat_interleave(torch.arange(bi.shape[0], device=bi.device), (bi >= 0).sum(dim=1))
        wa = torch.zeros(wi.shape[0], H, device=wi.device)
        ba = torch.zeros(bi.shape[0], H, device=bi.device)
        if wf.numel():
            wa.index_add_(0, rows_w, self.w1[wf])
        if bf.numel():
            ba.index_add_(0, rows_b, self.w1[bf])
        act = torch.clamp((wa + ba) * 32.0, -512.0, 512.0) / 512.0
        hidden = torch.clamp(act @ self.wh + self.bh, 0.0, 1.0)
        out = hidden @ self.w2.t()
        ph = phase.to(act.dtype) / 24.0
        return out[:, 0] * ph + out[:, 1] * (1.0 - ph)


TEST_FENS = [
    ("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "K+2R vs K"),
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "startpos"),
    ("4k3/8/8/8/8/8/8/RRR1K3 w Q - 0 1", "K+3R vs K"),
    ("3qk3/8/8/8/8/8/8/4K3 w - - 0 1", "black Q vs K"),
]


def print_sanity(net, name):
    net.eval()
    with torch.no_grad():
        for fen, label in TEST_FENS:
            w, b, ph = nt.fen_features(fen)
            wi = torch.full((1, 34), -1, dtype=torch.long)
            bi = torch.full((1, 34), -1, dtype=torch.long)
            wi[0, :len(w)] = torch.tensor(w)
            bi[0, :len(b)] = torch.tensor(b)
            phase = torch.tensor([float(ph)])
            ev = net(wi.to(device), bi.to(device), phase.to(device))
            print(f"[{name}] {label}: ~{ev.item()*600:.0f}cp", flush=True)
    net.train()


def run(net_cls, name, cache, results, scores, tr_sel, val_sel, loss_mode="per_row", bs=4096, lr=1e-2, wd=0.001):
    net = net_cls().to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=wd)
    warmup_epochs = max(3, epochs // 20)
    warmup = torch.optim.lr_scheduler.LinearLR(opt, start_factor=0.05, end_factor=1.0, total_iters=warmup_epochs)
    decay = torch.optim.lr_scheduler.StepLR(opt, step_size=max(epochs // 3, 1), gamma=0.4)
    sched = torch.optim.lr_scheduler.SequentialLR(opt, schedulers=[warmup, decay], milestones=[warmup_epochs])

    K = 6.0

    def loss_of(ev, r, sc):
        sig_r = torch.sigmoid(K * ev)
        l_wdl = (sig_r - r) ** 2
        target = torch.clamp(sc / 600.0, -12.0, 12.0)
        l_score = (ev - target) ** 2
        if loss_mode == "combined":
            # OLD behavior: every row gets both loss terms regardless of
            # whether it has a real result and/or a real score.
            return (l_wdl + l_score).mean()
        # NEW (per-row masked): each row only contributes the loss term(s)
        # for signals it actually has.
        r_mask = (torch.abs(r - 0.5) > 0.01).to(ev.dtype)
        sc_mask = (torch.abs(sc) > 0.01).to(ev.dtype)
        n_signals = (r_mask + sc_mask).clamp(min=1.0)
        return ((r_mask * l_wdl + sc_mask * l_score) / n_signals).mean()

    def sl(sel):
        return (torch.from_numpy(cache["wi"][sel]).to(device),
                torch.from_numpy(cache["bi"][sel]).to(device),
                torch.from_numpy(cache["ph"][sel]).to(device))

    def eval_val():
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

    rng = np.random.RandomState(11)
    best = 1e9
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
        vl = eval_val()
        best = min(best, vl)
        if (ep + 1) % 10 == 0 or ep == epochs - 1:
            print(f"[{name}] epoch {ep+1}: lr={opt.param_groups[0]['lr']:.5f} train={tot/max(nb,1):.4f} val={vl:.4f}", flush=True)
        sched.step()
    print(f"[{name}] FINAL best val loss: {best:.4f}", flush=True)
    print_sanity(net, name)
    return best


print("loading data...", flush=True)
cache, results, scores, has_scores = nt.load_data(path)
n_val = max(1, len(results) // 20)
val_sel = np.arange(0, n_val)
tr_sel = np.arange(n_val, len(results))
print(f"{len(tr_sel)} train / {len(val_sel)} val", flush=True)

# Isolation matrix: architecture x loss-selection-mode, one variable changed
# at a time, so a bad result can be attributed to a specific change instead
# of "something in the combination of everything changed at once" (exactly
# the failure mode that made the final full-scale run of the session
# uninterpretable). ONLY_2L_PER_ROW=1 runs just that one combo (used to test
# the same config against a different data sample without re-running all 4).
import os
results_table = {}
if os.environ.get("ONLY_2L_PER_ROW"):
    combos = [(Net2, "2-layer", "per_row")]
else:
    combos = [(nc, an, m) for nc, an in [(Net1, "1-layer"), (Net2, "2-layer")] for m in ["combined", "per_row"]]
wd_override = float(os.environ["WD"]) if os.environ.get("WD") else 0.001
for net_cls, arch_name, mode in combos:
    name = f"{arch_name}/{mode}"
    b = run(net_cls, name, cache, results, scores, tr_sel, val_sel, loss_mode=mode, wd=wd_override)
    results_table[name] = b

print("\n=== ISOLATION RESULT ===")
for name, b in results_table.items():
    print(f"{name}: best val {b:.4f}")
