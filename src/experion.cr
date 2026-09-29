# Experion — a UCI chess engine written in Crystal.
# Library entry: requires all engine modules. CLI lives in experion_cli.cr.

require "./experion/magic_constants"
require "./experion/types"
require "./experion/tables"
require "./experion/move"
require "./experion/psqt"
require "./experion/psqt_tuned"
require "./experion/position"
require "./experion/movegen"
require "./experion/perft"
require "./experion/eval"
require "./experion/tt"
require "./experion/nnue"
require "./experion/search"
require "./experion/san"
require "./experion/epdtest"
{% unless flag?(:win32) || flag?(:wasi) %}
require "./experion/gendata"
{% end %}

module Experion
  def self.init_engine : Nil
    Tables.init
    Zobrist.init
    Psqt.init
    # The release net is embedded; EXPERION_NNUE=/path/to/net.bin overrides it
    # (an empty value forces the classical evaluator).
    if p = ENV["EXPERION_NNUE"]?
      Nnue.load(p) unless p.empty?
    else
      Nnue.load_embedded
    end
    # optional override for tools (like epdtest) that don't go through the
    # UCI "setoption EvalBlend" path
    if b = ENV["EXPERION_BLEND"]?
      Nnue.set_blend(b.to_i? || 100)
    end
  end
end
