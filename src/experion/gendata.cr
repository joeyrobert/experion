# Self-play training data generator for Texel-style evaluation tuning.
#
#   experion gendata <games> <movetime_ms> <outfile> [threads]
#
# Emits one "FEN ;result" line per quiet position (result from white's
# perspective: 1.0 / 0.5 / 0.0).
#
# Worker threads are bare Threads (no execution context): they must NOT touch
# Crystal IO, so each collects samples in memory and the main thread writes
# the file after joining.

module Experion
  module GenData
    extend self
    include Moves

    # Classical-distillation mode: random-walk positions labeled with the
    # current classical evaluation (white POV centipawns). No searching —
    # produces millions of samples quickly so the NNUE can learn material,
# PSTs and basic terms before result-based fine-tuning.
    def run_classical(positions : Int32, path : String, threads : Int32 = 1) : Nil
      threads = threads.clamp(1, 16)
      per = positions // threads
      results = Array(Array(String)).new(threads) { Array(String).new }
      workers = Array(Thread).new(threads - 1)
      (1...threads).each do |i|
        workers << Thread.new do
          classical_worker(per, results[i], i + 1)
        end
      end
      classical_worker(per + positions % threads, results[0], 1)
      workers.each(&.join)
      File.open(path, "w") do |f|
        results.each { |r| r.each { |line| f.puts(line) } }
      end
      puts "generated #{positions} classical samples"
    end

    private def classical_worker(n : Int32, out_lines : Array(String), seed : Int32) : Nil
      rng = Random.new((0xABCD + seed * 104729).to_u64!)
      row = Pointer(Int32).malloc(Experion::Nnue.acc_row)
      n.times do
        pos = Experion::Position.startpos
        steps = 6 + rng.rand(110)
        steps.times do
          buf = Pointer(UInt16).malloc(MAX_MOVES)
          cnt = pos.generate(buf)
          break if cnt.zero?
          m = buf[rng.rand(cnt)]
          child = pos
          child.make_move(m, false)
          pos = child
          next if pos.in_check?

          # label from white POV using the classical eval
          base = Eval.evaluate(pos)
          label = pos.stm == WHITE.to_u8! ? base : -base
          next if label.abs > 1500

          parts = pos.to_fen.split
          out_lines << "#{parts[0]} #{parts[1]} #{parts[2]} #{parts[3]};0.5;#{label}"
        end
      end
    end

    # Scored-random mode: random-walk positions labeled by a FIXED-DEPTH
    # search score. Labels carry tactical information beyond the static
    # evaluator while remaining cheap enough to generate at scale.
    def run_scored(positions : Int32, depth : Int32, path : String, threads : Int32 = 1) : Nil
      threads = threads.clamp(1, 16)
      per = positions // threads
      done = Atomic(Int32).new(0)
      fds = Array(LibC::Int).new(threads, -1)
      files = Array(File).new(threads) { |i| File.new("#{path}.part#{i}", "w") }
      threads.times do |i|
        fds[i] = files[i].fd
      end

      workers = Array(Thread).new(threads - 1)
      (1...threads).each do |i|
        workers << Thread.new do
          scored_worker(per, depth, fds[i], i + 1)
          done.add(1)
        end
      end
      scored_worker(per + positions % threads, depth, fds[0], 1)
      done.add(1)
      workers.each(&.join)
      files.each(&.close)

      # merge parts
      File.open(path, "w") do |out_f|
        threads.times do |i|
          if File.exists?("#{path}.part#{i}")
            File.open("#{path}.part#{i}") { |pf| IO.copy(pf, out_f) }
            File.delete("#{path}.part#{i}")
          end
        end
      end
      lines = File.read_lines(path).size
      puts "generated #{done.get} games-worth, #{lines} scored samples"
    end

    private def scored_worker(n : Int32, depth : Int32, fd : LibC::Int, seed : Int32) : Nil
      rng = Random.new((0x51DE + seed * 7717).to_u64!)
      # 20 bits (1M entries) instead of 18: the table is reused across
      # thousands of distinct games without ever clearing entries from
      # unrelated games, and early-opening positions in particular recur
      # across nearly every game — a too-small table means heavy hash
      # collisions specifically for those frequently-revisited positions,
      # corrupting their scores in a consistent (not random) direction since
      # the same colliding slot keeps getting reused. new_game (below,
      # once per game) clears the cross-game corruption too.
      s = Searcher.new(TT.new(20))
      s.verbose = false
      limits = Limits.new
      limits.max_depth = depth.clamp(1, MAX_PLY - 8)
      # random-walk positions can occasionally be pathological (mass
      # promotions, bizarre material) and blow up search cost with no time
      # control in play; cap nodes so a single position can never hang the
      # whole generation run.
      limits.nodes_max = 300_000u64
      buf_str = IO::Memory.new
      emitted = 0

      flush = ->do
        slice = buf_str.to_slice
        LibC.write(fd, slice.to_unsafe.as(Void*), slice.size)
        buf_str.clear
      end

      n.times do
        s.new_game
        pos = Experion::Position.startpos
        steps = 4 + rng.rand(100)
        steps.times do
          buf = Pointer(UInt16).malloc(MAX_MOVES)
          cnt = pos.generate(buf)
          break if cnt.zero?
          m = buf[rng.rand(cnt)]
          child = pos
          child.make_move(m, false)
          pos = child
          next if pos.in_check?
          next if pos.halfmove > 60

          mv = s.think(pos, [] of UInt64, limits)
          next if mv == Moves::MOVE_NONE

          score_white = pos.stm == WHITE.to_u8! ? s.last_score : -s.last_score
          next if score_white.abs > 2500

          parts = pos.to_fen.split
          buf_str << parts[0] << ' ' << parts[1] << ' ' << parts[2] << ' ' <<
            parts[3] << ";0.5;" << score_white << '\n'
          emitted += 1
          flush.call if emitted % 4000 == 0
        end
      end
      flush.call
    end

    def run(games : Int32, movetime_ms : Int64, path : String, threads : Int32 = 1) : Nil
      threads = threads.clamp(1, 16)
      per = games // threads
      results = Array(Array(String)).new(threads) { |i| Array(String).new }
      done = Atomic(Int32).new(0)

      workers = Array(Thread).new(threads - 1)
      (1...threads).each do |i|
        workers << Thread.new do
          play_games(per, movetime_ms, results[i], i + 1)
          done.add(1)
        end
      end
      play_games(per + games % threads, movetime_ms, results[0], 1)
      done.add(1)

      workers.each(&.join)
      File.open(path, "w") do |f|
        results.each do |r|
          r.each { |line| f.puts(line) unless line.empty? }
        end
      end
      puts "generated #{done.get} games, #{results.sum(&.size)} samples"
    end

    private def play_games(n : Int32, movetime_ms : Int64, out_lines : Array(String), seed : Int32) : Nil
      rng = Random.new((0xC0FFEE + seed * 7919).to_u64!)
      s = Searcher.new(TT.new(20))
      s.verbose = false

      n.times do
        s.new_game
        pos = Position.startpos
        hashes = Array(UInt64).new

        plies = 4 + rng.rand(5)
        plies.times do
          buf = Pointer(UInt16).malloc(MAX_MOVES)
          cnt = pos.generate(buf)
          break if cnt.zero?
          m = buf[rng.rand(cnt)]
          child = pos
          child.make_move(m)
          hashes << pos.hash
          pos = child
        end

        samples = Array(String).new
        result = 0.5
        decided = false
        ply = 0

        loop do
          break if ply >= 240
          break if pos.halfmove >= 100
          break if Eval.insufficient_material?(pos)

          limits = Limits.new
          limits.soft_ms = movetime_ms
          limits.hard_ms = movetime_ms * 4
          mv = begin
            s.think(pos, hashes, limits)
          rescue
            Moves::MOVE_NONE
          end
          break if mv == Moves::MOVE_NONE

          score_white = pos.stm == WHITE.to_u8! ? s.last_score : -s.last_score
          from_sq = mv_from(mv)
          to_sq = mv_to(mv)
          is_ep = pos.piece_at(from_sq).to_i % 6 == PAWN &&
                  ((from_sq ^ to_sq) & 7) != 0 && pos.piece_at(to_sq) == NO_PIECE
          quiet = pos.piece_at(to_sq) == NO_PIECE && mv_promo_type(mv) == 0 &&
                  !pos.in_check? && pos.halfmove > 6 && !is_ep
          if quiet && score_white.abs < 1200 && ply > 8
            parts = pos.to_fen.split
            samples << "#{parts[0]} #{parts[1]} #{parts[2]} #{parts[3]};#{result_placeholder};#{score_white}"
          end

          child = pos
          child.make_move(mv)
          hashes << pos.hash
          pos = child
          ply += 1

          if pos.generate(Pointer(UInt16).malloc(MAX_MOVES)) == 0
            result = pos.in_check? ? (pos.stm == WHITE.to_u8! ? 0.0 : 1.0) : 0.5
            decided = true
            break
          end
        end

        result = 0.5 unless decided
        res_str = result.to_s
        samples.each do |line|
          parts = line.split(';')
          out_lines << "#{parts[0]};#{res_str};#{parts[2]}"
        end
      end
    end

    # Depth-limited self-play: real games (not random walks) labeled with the
    # engine's own search score and the eventual game result. Opening
    # diversity comes from a few random plies plus occasional non-best
    # moves, not from a second engine's eval.
    def run_selfplay(games : Int32, depth : Int32, path : String, threads : Int32 = 1) : Nil
      threads = threads.clamp(1, 16)
      openings = [] of String
      if op = ENV["EXPERION_OPENINGS"]?
        File.each_line(op) do |line|
          fen = line.strip
          openings << fen unless fen.empty? || fen.starts_with?('#')
        end
      end
      nodes = 350_000u64
      if s = ENV["EXPERION_SP_NODES"]?
        nodes = s.to_u64? || nodes
      end
      per = games // threads
      workers = Array(Thread).new(threads - 1)
      (1...threads).each do |i|
        workers << Thread.new do
          selfplay_worker(per, depth, "#{path}.#{i + 1}", i + 1, openings, nodes)
        end
      end
      selfplay_worker(per + games % threads, depth, "#{path}.1", 1, openings, nodes)
      workers.each(&.join)
      n_samples = 0
      File.open(path, "w") do |f|
        (1..threads).each do |i|
          part = "#{path}.#{i}"
          next unless File.exists?(part)
          File.each_line(part) do |line|
            next if line.empty?
            f.puts line
            n_samples += 1
          end
        end
      end
      puts "generated #{n_samples} samples from #{games} requested self-play games"
    end

    private def selfplay_worker(n : Int32, depth : Int32, part_path : String, seed : Int32, openings : Array(String), nodes : UInt64) : Nil
      rng = Random.new((0x51A7 + seed * 104729).to_u64!)
      s = Searcher.new(TT.new(20))
      s.verbose = false
      limits = Limits.new
      limits.max_depth = depth.clamp(4, 16)
      limits.nodes_max = nodes
      fd = LibC.open(part_path.check_no_null_byte, LibC::O_WRONLY | LibC::O_CREAT | LibC::O_TRUNC, 0o644)
      raise "open #{part_path} failed" if fd < 0
      buf = Pointer(UInt16).malloc(MAX_MOVES)
      book_mode = !openings.empty?

      n.times do |g|
        if (g & 3) == 3
          Raw.write_stdout("selfplay w#{seed} #{g + 1}/#{n}\n")
        end
        s.new_game
        pos = Position.startpos
        hashes = Array(UInt64).new
        if book_mode
          fen = openings[rng.rand(openings.size)]
          pos = begin
            Position.new(fen)
          rescue
            Position.startpos
          end
        else
          # A few random developing moves, not a 12-ply legal-move shuffle
          # (that produced instant miniature games and almost no samples).
          plies = 4 + rng.rand(4)
          plies.times do
            cnt = pos.generate(buf)
            break if cnt.zero?
            cap = Math.min(cnt, 12)
            m = buf[rng.rand(cap)]
            child = pos
            child.make_move(m)
            hashes << pos.hash
            pos = child
          end
        end

        samples = Array(String).new
        result = 0.5
        decided = false
        ply = 0
        loop do
          break if ply >= 160
          break if pos.halfmove >= 100
          break if Eval.insufficient_material?(pos)
          mv = begin
            s.think(pos, hashes, limits)
          rescue
            Moves::MOVE_NONE
          end
          break if mv == Moves::MOVE_NONE

          if ply < 12 && !pos.in_check? && rng.rand(100) < 12
            cnt = pos.generate(buf)
            mv = buf[rng.rand(cnt)] if cnt > 1
          end

          score_white = pos.stm == WHITE.to_u8! ? s.last_score : -s.last_score
          if score_white.abs < 8000
            parts = pos.to_fen.split
            samples << "#{parts[0]} #{parts[1]} #{parts[2]} #{parts[3]};#{score_white}"
          end
          # Adjudicate won games instead of burning 400k nodes × 160 plies
          # in a decided endgame (that stalled the 2k run at ~10 min/game).
          if ply >= 16 && score_white.abs >= 1500
            result = score_white > 0 ? 1.0 : 0.0
            decided = true
            break
          end

          child = pos
          child.make_move(mv)
          hashes << pos.hash
          pos = child
          ply += 1
          if pos.generate(buf) == 0
            result = pos.in_check? ? (pos.stm == WHITE.to_u8! ? 0.0 : 1.0) : 0.5
            decided = true
            break
          end
        end
        result = 0.5 unless decided
        buf_str = IO::Memory.new
        samples.each do |line|
          fen, score = line.split(';')
          buf_str << fen << ';' << result << ';' << score << '\n'
        end
        slice = buf_str.to_slice
        LibC.write(fd, slice.to_unsafe.as(Void*), slice.size) if slice.size > 0
      end
      LibC.close(fd)
    end

    private def result_placeholder : String
      "0.5"
    end
  end
end
