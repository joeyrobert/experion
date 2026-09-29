# Command-line interface for the Experion binary.

require "./experion"
require "./experion/bench"
require "./experion/uci"
{% unless flag?(:win32) %}
require "./experion/genficsdata"
require "./experion/scorefics"
{% end %}

module Experion
  # Runs a single fixed-movetime search and returns {completed_depth, nodes, ms}.
  # Used by the `smpdiag` diagnostic to measure the primary thread's real
  # throughput under a real time-based search, not fixed depth.
  def self.smpdiag_run_one(pos : Position, movetime : Int64) : {Int32, UInt64, Int64}
    limits = Limits.new
    limits.soft_ms = movetime
    limits.hard_ms = movetime
    s = Searcher.new
    s.verbose = false
    t0 = Time.instant
    s.think(pos, [] of UInt64, limits)
    dt = (Time.instant - t0).total_milliseconds.to_i64!
    {s.last_completed_depth, s.nodes, dt}
  end

  {% unless flag?(:win32) %}
  # Training-data tooling (POSIX file APIs); not part of the Windows build.
  def self.dev_tool(cmd : String?, args : Array(String)) : Bool
    case cmd
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
    when "gendata-selfplay"
      games = args[1]?.try(&.to_i?) || 2000
      depth = args[2]?.try(&.to_i?) || 8
      path = args[3]? || "training_selfplay.txt"
      thr = args[4]?.try(&.to_i?) || 8
      GenData.run_selfplay(games, depth, path, thr)
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
    else
      return false
    end
    true
  end
  {% else %}
  def self.dev_tool(cmd : String?, args : Array(String)) : Bool
    false
  end
  {% end %}

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
    when "nnuebench"
      Nnue.load(args[1]) || abort("cannot load net")
      pos = Position.new("r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10")
      a = Pointer(Int32).malloc(Nnue.acc_row)
      b = Pointer(Int32).malloc(Nnue.acc_row)
      t = Time.instant
      200_000.times { Nnue.refresh(a, pos) }
      puts "refresh: #{((Time.instant - t).total_nanoseconds / 200_000).round(0)} ns"
      t = Time.instant
      sink = 0
      2_000_000.times { |i| sink += Nnue.evaluate(a, 20, i.odd?, 30) }
      puts "evaluate: #{((Time.instant - t).total_nanoseconds / 2_000_000).round(0)} ns (#{sink})"
      t = Time.instant
      2_000_000.times { |i| Nnue.apply_delta(b, a, 100, 200, 0, 0, 300, 400, 0, 0, 1, 1) }
      puts "apply_delta(1rm+1add): #{((Time.instant - t).total_nanoseconds / 2_000_000).round(0)} ns"
    when "bench"
      Bench.run(args[1]?.try(&.to_i?) || 0)
    when "epdtest"
      path = args[1]? || "suites/wac.epd"
      ms = args[2]?.try(&.to_i?) || 200
      maxn = args[3]?.try(&.to_i?) || 0
      EpdTest.run(path, ms.to_i64!, maxn)
    when "smpdiag"
      # Phase 1 SMP diagnostic: measure the PRIMARY thread's real nodes/
      # depth/nps for a fixed movetime, once solo and once with N-1 worker
      # threads concurrently active (each worker gets its own isolated TT,
      # so this isolates hardware/OS contention from shared-TT effects,
      # which were already ruled out separately this session).
      #   experion smpdiag <threads> <movetime_ms> [fen]
      threads = args[1]?.try(&.to_i?) || 4
      movetime = (args[2]?.try(&.to_i?) || 2000).to_i64!
      fen = args[3]? || STARTPOS_FEN
      pos = Position.new(fen)

      depth0, nodes0, ms0 = smpdiag_run_one(pos, movetime)
      nps0 = ms0 > 0 ? nodes0 * 1000 // ms0 : nodes0
      printf("solo:       depth=%d nodes=%d time=%dms nps=%d\n", depth0, nodes0, ms0, nps0)

      if threads > 1
        stop = SearchStop.new
        workers = Array(Thread).new(threads - 1)
        (1...threads).each do |i|
          workers << Thread.new do
            w = Searcher.new(TT.new, stop, i % 2)
            w.verbose = false
            w.raw_output = true
            limits = Limits.new
            limits.soft_ms = movetime
            limits.hard_ms = movetime
            w.think(pos, [] of UInt64, limits)
          end
        end
        depth1, nodes1, ms1 = smpdiag_run_one(pos, movetime)
        stop.set(true)
        workers.each(&.join)
        nps1 = ms1 > 0 ? nodes1 * 1000 // ms1 : nodes1
        printf("w/%d workers: depth=%d nodes=%d time=%dms nps=%d\n", threads - 1, depth1, nodes1, ms1, nps1)
        printf("primary nps ratio (concurrent/solo): %.2f\n", nps1.to_f / nps0)
      end
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
      Uci.run unless dev_tool(cmd, args)
    end
    0
  end
end

Experion.main(ARGV)
