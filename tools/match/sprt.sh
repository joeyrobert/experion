#!/bin/zsh
# Self-play SPRT: candidate (bin/experion) vs baseline (bin/experion_baseline).
#
# This exists because fixed-round-count ladder tests (run_match.sh) are too
# noisy to trust for small/uncertain changes — this project's own findings
# doc documents 10-16 game samples swinging 6%-24% for the IDENTICAL
# config, and Phase 2's reverted time-management change had only a single
# 30-game sample as evidence either way. SPRT (fastchess's built-in
# `-sprt`) tests directly against a null hypothesis (elo0) vs an
# alternative (elo1) and stops as soon as the result is statistically
# significant, rather than committing to a fixed sample size up front.
#
# usage: sprt.sh [tc] [elo0] [elo1]
#   elo0/elo1 default to 0/5 — "is the candidate at least neutral, or up to
#   +5 Elo" — a standard non-regression-or-small-gain test. Use elo0=-5
#   elo1=0 to specifically test "did this regress".
#
# Before testing a change: `cp bin/experion bin/experion_baseline` to save
# the last validated build, THEN make your change and rebuild bin/experion.
# After a change is validated (SPRT accepts H1) or rejected (accepts H0),
# re-snapshot the new baseline for the next change.
set -e
BASE=/Users/joey/Repos/experion
FC=$BASE/tools/match/fastchess-mac-arm64/fastchess

TC=${1:-10+0.1}
ELO0=${2:-0}
ELO1=${3:-5}

if [[ ! -f $BASE/bin/experion_baseline ]]; then
  echo "no bin/experion_baseline found — run: cp bin/experion bin/experion_baseline (before your change)"
  exit 1
fi

$FC \
  -engine cmd=$BASE/bin/experion name=Candidate \
  -engine cmd=$BASE/bin/experion_baseline name=Baseline \
  -each tc="$TC" option.Threads=${THREADS:-4} option.Hash=256 \
  -openings file=$BASE/tools/match/openings.pgn format=pgn order=random \
  -sprt elo0=$ELO0 elo1=$ELO1 alpha=0.05 beta=0.05 model=normalized \
  -rounds ${ROUNDS:-2000} -games 2 -repeat -concurrency ${CONC:-1} \
  -ratinginterval 10 \
  -pgnout file=$BASE/tools/match/sprt_games.pgn notation=uci append=true \
  -output format=cutechess
