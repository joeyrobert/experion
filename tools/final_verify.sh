#!/bin/zsh
# Post-tune verification: rebuild, specs, quick suites, crafty match.
set -e
BASE=/Users/joey/Repos/experion
cd $BASE
crystal build --release -o bin/experion_v2 src/experion_cli.cr
cp bin/experion_v2 bin/experion
crystal spec 2>&1 | tail -1
./bin/experion epdtest suites/wac.epd 200 2>/dev/null | tail -1
CONC=1 zsh tools/match/run_match.sh 10+0.1 20 crafty 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -E "Score of|Elo diff"
