#!/bin/zsh
# Full tuning cycle: tune PSQT on training data, rebuild, quick gauntlet.
set -e
BASE=/Users/joey/Repos/experion
cd $BASE

echo "== tuning =="
crystal run tools/texel_tune.cr --release -- ${1:-/tmp/training.txt} 60 8000 1.13

echo "== rebuild =="
crystal build --release -o bin/experion_v2 src/experion_cli.cr

echo "== WAC sanity =="
./bin/experion_v2 epdtest suites/wac.epd 200 2>/dev/null | tail -1

echo "== specs =="
crystal spec 2>&1 | tail -1
