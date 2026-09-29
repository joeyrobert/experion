#!/usr/bin/env python3
"""History-gravity canary on mix25. Revert the binary if Fruit dies.

Does not rematch mix25 without this change. LMP2 12/18/24/32 was 17.5%.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wait_sp as wsp  # noqa: E402

BASE = wsp.BASE
MIX25 = wsp.MIX25
HERE = Path(__file__).resolve().parent
LOG = HERE / "wait_histgrav.log"
SEARCH = BASE / "src" / "experion" / "search.cr"
wsp.LOG = LOG


def say(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(msg, flush=True)


wsp.say = say


def rebuild() -> bool:
    say("shards build --release")
    log = open(HERE / "histgrav_build.out", "w", buffering=1)
    r = subprocess.run(
        ["caffeinate", "-i", "shards", "build", "--release"],
        cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT,
    )
    say(f"build rc={r.returncode}")
    return r.returncode == 0


def revert() -> None:
    t = SEARCH.read_text()
    t = t.replace("    HIST_N       = 768  # 12 piece codes * 64 target squares\n    HIST_MAX     = 8_000_000\n",
                  "    HIST_N       = 768  # 12 piece codes * 64 target squares\n")
    t = t.replace(
        """    # Stockfish-style gravity so a few cutoffs cannot pin history at the cap.
    private def apply_gravity(h : Int32, bonus : Int32) : Int32
      (h.to_i64! + bonus.to_i64! - h.to_i64! * bonus.abs // HIST_MAX).to_i32!
    end

    private def bump_history(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      @history[idx] = apply_gravity(@history[idx], depth * depth)
    end

    private def bump_history_down(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      @history[idx] = apply_gravity(@history[idx], -(depth * depth))
    end

    private def bump_cap_history(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      @cap_hist[idx] = apply_gravity(@cap_hist[idx], depth * depth)
    end
""",
        """    private def bump_history(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      v = @history[idx] + depth * depth
      @history[idx] = v > 8_000_000 ? 8_000_000 : v
    end

    private def bump_history_down(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      v = @history[idx] - depth * depth
      @history[idx] = v < -8_000_000 ? -8_000_000 : v
    end

    private def bump_cap_history(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      v = @cap_hist[idx] + depth * depth
      @cap_hist[idx] = v > 8_000_000 ? 8_000_000 : v
    end
""",
    )
    t = t.replace(
        "@conthist[chi] = apply_gravity(@conthist[chi], depth * depth)",
        "v = @conthist[chi] + depth * depth\n                    @conthist[chi] = v > 8_000_000 ? 8_000_000 : v",
    )
    t = t.replace(
        "@conthist[chi] = apply_gravity(@conthist[chi], -(depth * depth))",
        "v = @conthist[chi] - depth * depth\n              @conthist[chi] = v < -8_000_000 ? -8_000_000 : v",
    )
    SEARCH.write_text(t)
    say("reverted history gravity")
    rebuild()


def main() -> None:
    say("wait_histgrav: gravity history vs Fruit on mix25")
    while wsp.fastchess_up():
        say("waiting for fastchess")
        time.sleep(15)
    if "apply_gravity" not in SEARCH.read_text():
        say("gravity not in search.cr")
        return
    if not rebuild():
        say("build failed")
        revert()
        return
    sc = wsp.fruit_then_crafty(MIX25, "mix25_histgrav", fruit_bar=0.18)
    if sc and sc[3] >= 0.45 and sc[4] >= 36:
        say("histgrav cleared Fruit")
        return
    if not sc or sc[3] < 0.22 or sc[4] < 18:
        say("histgrav failed Fruit; revert")
        revert()
    last = 0.0
    while True:
        if wsp.cluster_up():
            say("llama is up")
            return
        now = time.time()
        if now - last >= 300:
            say("llama still down")
            last = now
        time.sleep(60)


if __name__ == "__main__":
    main()
