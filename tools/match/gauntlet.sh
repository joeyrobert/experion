#!/bin/sh
# Gauntlet: Experion vs each of the three milestone targets, in sequence.
#
# usage: gauntlet.sh [tc] [games-per-opponent] [concurrency] [opponents...]
#   defaults: 10+0.1 400 4  "glaurung wyld stash"
#   e.g. gauntlet.sh 10+0.1 400 8
#        gauntlet.sh 60+0.6 200 4 stash
#
# THREADS=1 and HASH=64 are baked in (the measuring rule from
# docs/plans/2026_10_27_BEAT_GLAURUNG_WYLD_STASH.md: every comparison in
# this plan is single-thread, like for like). Games are played in
# colour-swapped pairs from openings.pgn. Each opponent gets its own PGN
# file (match/gauntlet_<opponent>.pgn) so the shared games.pgn stops growing.
#
# Prints fastchess's W-L-D / score / Elo +/- summary per opponent, plus a
# compact recap table.
set -e
BASE=$(cd "$(dirname "$0")/../.." && pwd)
case "$(uname -s)" in
  Darwin) FC=${FC:-$BASE/tools/match/fastchess-mac-arm64/fastchess} ;;
  *)      FC=${FC:-$BASE/tools/match/fastchess-linux/fastchess} ;;
esac

TC=${1:-10+0.1}
GAMES=${2:-400}
CONC=${3:-4}
OPPS=${4:-"glaurung wyld stash"}
ROUNDS=$((GAMES / 2))

ENG=${EXPERION_BIN:-$BASE/bin/experion}

# opponent name -> "<binary> [extra engine args]" mirroring run_match.sh cases.
# glaurung: Threads default is 4 and Ponder default true; its stall history
# (class_glaurung.log) is fixed by pinning both and giving a time margin.
opp_case() {
  case "$1" in
    glaurung) echo "$BASE/tools/match/ladder/glaurung22 option.Ponder=false" ;;
    wyld)     echo "$BASE/tools/match/ladder/wyldchess151" ;;
    stash)    echo "$BASE/tools/match/ladder/stash21" ;;
    *)        echo "" ;;
  esac
}

SUMMARY=$BASE/tools/match/gauntlet_summary.txt
: > "$SUMMARY"

for OPP in $OPPS; do
  OPP_SPEC=$(opp_case "$OPP")
  if [ -z "$OPP_SPEC" ]; then
    echo "unknown opponent: $OPP" >&2
    exit 1
  fi
  OPP_BIN=$(echo "$OPP_SPEC" | cut -d' ' -f1)
  OPP_ARGS=$(echo "$OPP_SPEC" | cut -s -d' ' -f2-)
  case "$OPP" in
    glaurung) OPP_NAME=Glaurung22_CCRL2911 ;;
    wyld)     OPP_NAME=WyldChess151_CCRL2679 ;;
    stash)    OPP_NAME=Stash21_CCRL2710 ;;
    *)        OPP_NAME=$OPP ;;
  esac

  PGN=$BASE/tools/match/gauntlet_${OPP}.pgn
  echo "===== gauntlet: Experion vs $OPP_NAME ($TC, ${GAMES} games, Threads=1 Hash=64) ====="
  $FC \
    -engine cmd=$ENG name=Experion \
    -engine cmd=$OPP_BIN name=$OPP_NAME ${OPP_ARGS:+$OPP_ARGS} \
    -each tc="$TC" option.Threads=1 option.Hash=64 timemargin=20 \
    -rounds "$ROUNDS" -games 2 -repeat \
    -openings file=$BASE/tools/match/openings.pgn format=pgn order=random \
    -ratinginterval 20 -concurrency "$CONC" \
    -pgnout file=$PGN notation=uci append=true \
    -output format=cutechess \
    -recover \
    -maxmoves 300 2>&1 | tee "$BASE/tools/match/gauntlet_${OPP}.log" | grep -E "^(Score of|Elo difference|SPRT)" || true
  grep -E "^(Score of|Elo difference)" "$BASE/tools/match/gauntlet_${OPP}.log" >> "$SUMMARY" || true
done

echo
echo "===== gauntlet recap ====="
cat "$SUMMARY"
