#!/bin/zsh
# Wrapper so fastchess-spawned Experion always sees the NNUE net.
export EXPERION_NNUE=${EXPERION_NNUE:-/Users/joey/Repos/experion/nets/enn4_w192all.bin}
export EXPERION_BLEND=${EXPERION_BLEND:-100}
exec /Users/joey/Repos/experion/bin/experion "$@"
