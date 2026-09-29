#!/usr/bin/env python3
"""Logistic Elo from W-L-D scores, plus a one-parameter MLE vs fixed opponents.

delta = 400 * log10(s / (1-s))
SE uses binomial score variance times d(delta)/ds.
Draws count as half a point. This is the FIDE/CCRL logistic, not Glicko.
"""
from __future__ import annotations

import math
import re
from pathlib import Path


def score(w: int, l: int, d: int) -> float:
    n = w + l + d
    return (w + 0.5 * d) / n if n else float("nan")


def elo_delta(s: float) -> float:
    if s <= 0.0:
        return -999.0
    if s >= 1.0:
        return 999.0
    return 400.0 * math.log10(s / (1.0 - s))


def elo_se(s: float, n: int) -> float:
    if n <= 0 or s <= 0.0 or s >= 1.0:
        return float("nan")
    se_s = math.sqrt(s * (1.0 - s) / n)
    deriv = 400.0 / (math.log(10.0) * s * (1.0 - s))
    return deriv * se_s


def parse_fastchess_score(path: Path):
    text = path.read_text(errors="replace") if path.exists() else ""
    lines = [ln for ln in text.splitlines() if "Score of Experion" in ln]
    if not lines:
        return None
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+).*?\[([0-9.]+)\]\s+(\d+)", lines[-1])
    if not m:
        return None
    w, l, d, s, n = int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4)), int(m.group(5))
    return {"w": w, "l": l, "d": d, "s": s, "n": n, "line": lines[-1]}


def mle_rating(obs, lo=1500.0, hi=3600.0, steps=400):
    """obs: list of {rating, w, l, d}. Opponent ratings held fixed."""
    best_r, best_ll = None, -1e300
    for i in range(steps + 1):
        r = lo + (hi - lo) * i / steps
        ll = 0.0
        for o in obs:
            n = o["w"] + o["l"] + o["d"]
            if n == 0:
                continue
            s = score(o["w"], o["l"], o["d"])
            expected = 1.0 / (1.0 + 10.0 ** ((o["rating"] - r) / 400.0))
            expected = min(max(expected, 1e-6), 1.0 - 1e-6)
            ll += n * (s * math.log(expected) + (1.0 - s) * math.log(1.0 - expected))
        if ll > best_ll:
            best_ll, best_r = ll, r
    return best_r, best_ll


def residual(r: float, o) -> float:
    s = score(o["w"], o["l"], o["d"])
    expected = 1.0 / (1.0 + 10.0 ** ((o["rating"] - r) / 400.0))
    return (s - expected) * 100.0


if __name__ == "__main__":
    base = Path("/Users/joey/Repos/experion/tools/match")
    # Historical mixed-net results. Overridden below when a ship-net log exists.
    matches = [
        {"name": "Vice 1.1", "ccrl": 1997, "w": 16, "l": 4, "d": 0, "note": "floor",
         "log": "class_vice.log"},
        {"name": "Sungorus 1.4", "ccrl": 2268, "w": 0, "l": 0, "d": 0, "note": "peer; ship-net pending",
         "log": "class_sungorus.log"},
        {"name": "BBC 1.2", "ccrl": 2465, "w": 15, "l": 3, "d": 2, "note": "CCRL slot is BBChess 1.3b",
         "log": "class_bbc.log"},
        {"name": "Fruit 2.1", "ccrl": 2694, "w": 2, "l": 18, "d": 0, "note": "boss; not on 2026 best-versions",
         "log": "class_fruit.log"},
        {"name": "GNU Chess 6.3.0", "ccrl": 2823, "w": 3, "l": 16, "d": 1, "note": "boss; list is 5.60",
         "log": "class_gnuchess.log"},
        {"name": "Glaurung 2.2", "ccrl": 2911, "w": 0, "l": 0, "d": 0, "note": "invalid: disconnects",
         "log": ""},
        {"name": "Crafty 25.2", "ccrl": 3040, "w": 17, "l": 17, "d": 6, "note": "local even; not CCRL 4CPU",
         "log": "crafty_w192all.log+crafty_w192allb.log"},
    ]
    print(f"{'opponent':<22} {'CCRL':>5} {'W-L-D':>12} {'score':>7} {'ΔElo':>7} {'±95%':>7} {'implied':>8}  note")
    obs = []
    for m in matches:
        if m["log"]:
            parts = [p.strip() for p in m["log"].split("+") if p.strip()]
            if len(parts) > 1:
                w = l = d = 0
                ok = True
                for p in parts:
                    parsed = parse_fastchess_score(base / p)
                    if not parsed:
                        ok = False
                        break
                    w += parsed["w"]
                    l += parsed["l"]
                    d += parsed["d"]
                if ok and w + l + d >= 10:
                    m["w"], m["l"], m["d"] = w, l, d
                    m["note"] = f"ship net, {w + l + d}g"
            else:
                parsed = parse_fastchess_score(base / parts[0])
                if parsed and parsed["n"] >= 10:
                    m["w"], m["l"], m["d"] = parsed["w"], parsed["l"], parsed["d"]
                    m["note"] = f"ship net, {parsed['n']}g"
        n = m["w"] + m["l"] + m["d"]
        if n == 0:
            print(f"{m['name']:<22} {m['ccrl']:5d} {'—':>12} {'—':>7} {'—':>7} {'—':>7} {'—':>8}  {m['note']}")
            continue
        s = score(m["w"], m["l"], m["d"])
        dlt = elo_delta(s)
        se = elo_se(s, n)
        implied = m["ccrl"] + dlt
        ci = 1.96 * se if se == se else float("nan")
        print(f"{m['name']:<22} {m['ccrl']:5d} {m['w']:2d}-{m['l']:<2d}-{m['d']:<2d} {100*s:6.1f}% {dlt:+7.0f} {ci:7.0f} {implied:8.0f}  {m['note']}")
        obs.append({"rating": m["ccrl"], "w": m["w"], "l": m["l"], "d": m["d"], "name": m["name"], "hang": "hang" in m["note"]})
    if obs:
        r, ll = mle_rating(obs)
        print(f"\nMLE vs all CCRL anchors: {r:.0f}  (loglik {ll:.1f})")
        obs2 = [o for o in obs if not o.get("hang")]
        r2, _ = mle_rating(obs2)
        print(f"MLE dropping Sungorus:   {r2:.0f}")
        print("Residuals at all-anchor MLE (score − expected), percentage points:")
        for o in obs:
            print(f"  {o['name']:<22} {residual(r, o):+6.1f} pp")

