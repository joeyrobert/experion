#!/bin/zsh
# Head-to-head match runner (fastchess).
#
# usage: run_match.sh [tc] [rounds]
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
  gnuchess)  OPP_BIN=$(which gnuchess); OPP_NAME=GNUChess; OPP_ARGS="" ;;
  ruffian)   OPP_BIN=$BASE/tools/match/uci_bridge; OPP_NAME=Ruffian; OPP_ARGS=$BASE/tools/match/ruffian ;;
  *)         OPP_BIN=$3; OPP_NAME=${3:t}; OPP_ARGS="" ;;
esac

$FC \
  -engine cmd=$BASE/bin/experion name=Experion \
  -engine cmd=$OPP_BIN name=$OPP_NAME ${OPP_ARGS:+args="$OPP_ARGS"} \
  -each tc="$TC" option.Threads=8 option.Hash=256 \
  -rounds "$ROUNDS" -games 2 -repeat \
  -openings file=$BASE/tools/match/openings.pgn format=pgn order=random \
  -ratinginterval 10 -concurrency ${CONC:-2} \
  -pgnout file=$BASE/tools/match/games.pgn notation=uci append=true \
  -output format=cutechess
