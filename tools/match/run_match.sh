#!/bin/zsh
# Head-to-head match runner (fastchess).
#
# usage: run_match.sh [tc] [rounds]
#
# THREADS defaults to 1: lazy-SMP (think_smp in search.cr) measurably HURTS
# play quality (17.5% vs Vice single-threaded, ~0% at Threads=8 in the same
# match setup) — root cause not yet diagnosed (suspected: worker threads
# polluting the shared TT with entries from more-aggressively-reduced,
# lower-quality searches, since TT replacement favors "deeper" entries by
# nominal depth regardless of how much real work produced them). Override
# with THREADS=N only once that's fixed and re-validated.
set -e
BASE=/Users/joey/Repos/experion
FC=$BASE/tools/match/fastchess-mac-arm64/fastchess
BRIDGE=$BASE/tools/match/uci_bridge

TC=${1:-10+0.1}
ROUNDS=${2:-50}
# opponent selection: tscp | cerulean | crafty | gnuchess
case ${3:-tscp} in
  tscp)      OPP_BIN=$BASE/tools/match/uci_bridge; OPP_NAME=TSCP181; OPP_ARGS=$BASE/tools/match/tscp181 ;;
  cerulean)  OPP_BIN=$BASE/tools/match/uci_bridge; OPP_NAME=CeruleanJS; OPP_ARGS="node /Users/joey/Repos/ceruleanjs/src/index.js" ;;
  crafty)    OPP_BIN=$BASE/tools/match/uci_bridge; OPP_NAME=Crafty252; OPP_ARGS="--needs-restart $BASE/tools/match/Crafty-Chess-25.2/crafty252" ;;
  fruit)     OPP_BIN=/Users/joey/Repos/engines/fruit/src/fruit; OPP_NAME=Fruit21_CCRL2694; OPP_ARGS="" ;;
  gnuchess)  OPP_BIN=$(which gnuchess); OPP_NAME=GNUChess; OPP_ARGS="" ;;
  ruffian)   OPP_BIN=$BASE/tools/match/uci_bridge; OPP_NAME=Ruffian; OPP_ARGS=$BASE/tools/match/ruffian ;;
  vice)      OPP_BIN=$BASE/tools/match/ladder/vice11; OPP_NAME=Vice11_CCRL1997; OPP_ARGS="" ;;
  sungorus)  OPP_BIN=$BASE/tools/match/ladder/sungorus14; OPP_NAME=Sungorus14_CCRL2269; OPP_ARGS="" ;;
  bbc)       OPP_BIN=$BASE/tools/match/ladder/bbc12; OPP_NAME=BBC12_ApproxCCRL2465; OPP_ARGS="" ;;
  *)         OPP_BIN=$3; OPP_NAME=${3:t}; OPP_ARGS="" ;;
esac

$FC \
  -engine cmd=$BASE/bin/experion name=Experion ${BLEND:+option.EvalBlend=$BLEND} \
  -engine cmd=$OPP_BIN name=$OPP_NAME ${OPP_ARGS:+args="$OPP_ARGS"} \
  -each tc="$TC" option.Threads=${THREADS:-1} option.Hash=256 \
  -rounds "$ROUNDS" -games 2 -repeat \
  -openings file=$BASE/tools/match/openings.pgn format=pgn order=random \
  -ratinginterval 10 -concurrency ${CONC:-2} \
  -pgnout file=$BASE/tools/match/games.pgn notation=uci append=true \
  -output format=cutechess
