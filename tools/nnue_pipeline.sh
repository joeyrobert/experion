#!/bin/zsh
# Train NNUE on scored data, install, verify, match vs Crafty.
# usage: nnue_pipeline.sh [data] [epochs] [init.state]
set -e
BASE=/Users/joey/Repos/experion
cd $BASE

echo "== training =="
python3 tools/nnue_train.py ${1:-/tmp/training_scored.txt} ${2:-50} src/experion/nnue.bin ${3:+init=$3}

cp src/experion/nnue.bin $BASE/nnue.bin

echo "== rebuild + specs =="
crystal build --release -o bin/experion src/experion_cli.cr
crystal spec 2>&1 | tail -1

echo "== eval sanity =="
crystal run scratch/nnue_eval_check.cr --release

echo "== crafty match =="
CONC=1 zsh tools/match/run_match.sh 10+0.1 20 crafty 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -E "Score of|Elo diff" | tail -4
