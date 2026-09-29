# WebAssembly (WASI) entry point: the UCI loop on a preloaded stdin script.
# Built with tools/build_wasm.sh; driven by site/play/engine-worker.js.

require "./experion"
require "./experion/uci"

Experion.init_engine
Experion::Uci.run
