# Command-line interface for the Experion binary.

require "./experion"
require "./experion/bench"
require "./experion/uci"
require "./experion/genficsdata"
require "./experion/scorefics"

module Experion
  def self.main(args : Array(String)) : Int32
    init_engine
    cmd = args[0]?

    case cmd
    when "perft"
      depth = args[1]?.try(&.to_i?) || 4
      fen = args[2]? || STARTPOS_FEN
      pos = Position.new(fen)
      t = Time.instant
      nodes = Perft.run(pos, depth)
      dt = Time.instant - t
      printf("perft(%d) = %d  (%.3fs, %.1f Mnps)\n", depth, nodes, dt.total_seconds, nodes / dt.total_milliseconds / 1000)
    when "divide"
      depth = args[1]?.try(&.to_i?) || 1
      fen = args[2]? || STARTPOS_FEN
      Perft.divide(Position.new(fen), depth)
    when "listmoves"
      fen = args[1]? || STARTPOS_FEN
      puts Position.new(fen).legal_moves_string
    when "batchmoves"
      STDIN.each_line do |line|
        fen = line.strip
        next if fen.empty?
        print Position.new(fen).legal_moves_string
        print "\n"
      end
    when "bench"
      Bench.run(args[1]?.try(&.to_i?) || 0)
    when "epdtest"
      path = args[1]? || "suites/wac.epd"
      ms = args[2]?.try(&.to_i?) || 200
      maxn = args[3]?.try(&.to_i?) || 0
      EpdTest.run(path, ms.to_i64!, maxn)
    when "gendata"
      games = args[1]?.try(&.to_i?) || 500
      ms = (args[2]?.try(&.to_i?) || 200).to_i64!
      path = args[3]? || "training.txt"
      thr = args[4]?.try(&.to_i?) || 1
      GenData.run(games, ms, path, thr)
    when "gendata-scored"
      n = args[1]?.try(&.to_i?) || 400000
      d = args[2]?.try(&.to_i?) || 10
      path = args[3]? || "training_scored.txt"
      thr = args[4]?.try(&.to_i?) || 8
      GenData.run_scored(n, d, path, thr)
    when "gendata-classical"
      n = args[1]?.try(&.to_i?) || 200000
      path = args[2]? || "training_classical.txt"
      thr = args[3]?.try(&.to_i?) || 8
      GenData.run_classical(n, path, thr)
    when "genfics-data"
      in_path = args[1]? || raise "missing input pgn path"
      out_path = args[2]? || "training_fics.txt"
      target = args[3]?.try(&.to_i?) || 100000
      min_ply = args[4]?.try(&.to_i?) || 16
      max_ply = args[5]?.try(&.to_i?) || 120
      GenFicsData.run(in_path, out_path, target, min_ply, max_ply)
    when "score-fics"
      in_path = args[1]? || raise "missing input txt path"
      out_path = args[2]? || "training_fics_scored.txt"
      ScoreFics.run(in_path, out_path)
    when "search"
      # quick non-UCI search test: experion search <depth> <fen>
      depth = args[1]?.try(&.to_i?) || 8
      fen = args[2]? || STARTPOS_FEN
      limits = Limits.new
      limits.max_depth = depth.clamp(1, MAX_PLY - 8)
      best = Searcher.new.think(Position.new(fen), [] of UInt64, limits)
      puts "bestmove #{Moves.mv_uci(best)}"
    else
      # engines are expected to speak UCI on bare invocation
      Uci.run
    end
    0
  end
end

Experion.main(ARGV)
