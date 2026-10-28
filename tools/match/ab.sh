#!/bin/sh
# A/B self-play between two env configurations of the same binary.
# (POSIX sh so this runs on Linux boxes too; fine under bash/zsh on macOS.)
#
# usage: ab.sh "<envA assignments>" "<envB assignments>" [rounds] [tc]
#   e.g. ab.sh "EXPERION_NNUE=nets/a.bin" "EXPERION_NNUE=nets/b.bin EXPERION_NO_OVERLAY=1" 100 8+0.08
# Single-threaded engines, CONC games at a time. Score is A vs B.
set -e
BASE=${BASE:-$(cd "$(dirname "$0")/../.." && pwd)}
case "$(uname -s)" in
  Darwin) FC=${FC:-$BASE/tools/match/fastchess-mac-arm64/fastchess} ;;
  *)      FC=${FC:-$BASE/tools/match/fastchess-linux/fastchess} ;;
esac
ENVA=$1
ENVB=$2
ROUNDS=${3:-100}
TC=${4:-8+0.08}
BIN=${EXPERION_BIN:-$BASE/bin/experion}
TMP=${TMPDIR:-/tmp}
printf '#!/bin/sh\nexport EXPERION_BLEND=100 %s\ncd %s\nexec %s "$@"\n' "$ENVA" "$BASE" "$BIN" > $TMP/ab_a.sh
printf '#!/bin/sh\nexport EXPERION_BLEND=100 %s\ncd %s\nexec %s "$@"\n' "$ENVB" "$BASE" "$BIN" > $TMP/ab_b.sh
chmod +x $TMP/ab_a.sh $TMP/ab_b.sh
$FC \
  -engine cmd=$TMP/ab_a.sh name=A \
  -engine cmd=$TMP/ab_b.sh name=B \
  -each tc="$TC" option.Threads=1 option.Hash=64 \
  -rounds "$ROUNDS" -games 2 -repeat \
  -openings file=$BASE/tools/match/openings.pgn format=pgn order=random \
  -ratinginterval 20 -concurrency ${CONC:-5} \
  -output format=cutechess -recover -maxmoves 300
