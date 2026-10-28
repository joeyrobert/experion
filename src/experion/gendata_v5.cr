# Binary self-play data generator for the ENN5 trainer ("gendata-v5").
#
#   experion gendata-v5 <target_positions> <out_dir> [threads]
#
# Plays self-play games with a fixed NODE budget per move (default 5k, with
# 10k for a 20% sample), labels each quiet position with the search score
# from the side-to-move's POV plus the eventual game result, and appends
# fixed-width 64-byte records to per-worker part files in out_dir. Run it
# again with the same out_dir to resume (existing records are counted and
# the target is treated as cumulative). Part files rotate at 128 MB. Pack
# the result for train_v5.py with tools/pack_v5.py.
#
# Tuning knobs (all ENV, all optional):
#   EXPERION_V5_NODES        base node budget per move       (default 5000)
#   EXPERION_V5_NODES_BIG    sampled node budget per move    (default 10000)
#   EXPERION_V5_SAMPLE_PCT   % of moves using the big budget (default 20)
#   EXPERION_V5_OPEN_PLIES   random plies before the game    (default 8)
#   EXPERION_V5_DISCARD_CP   discard games whose opening position scores outside ±400 (default 400)
#   EXPERION_V5_MAXPLY       ply cap                         (default 240)
#   EXPERION_V5_RANDOM_PCT   % of first 10 moves replaced by a random legal move (default 10)
#   EXPERION_OPENINGS        file of FENs; games start from one (optional)
#
# Record layout (64 bytes, little-endian):
#   0..31   packed board: byte j = low nibble sq 2j, high nibble sq 2j+1;
#           codes 0-5 white P N B R Q K, 6-11 black, 12 empty (matches
#           train_v5.py / merge_v5.py exactly)
#   32..39  position hash u64 (Position#hash, for global dedup)
#   40      stm byte (1 = black to move; == trainer flags bit0)
#   41      final game result, white POV (0 black win, 1 draw, 2 white win)
#   42..43  score i16, white POV centipawns (search score for the side to move, before the best move)
#   44..45  ply u16
#   46..47  completed search depth u16
#   48..55  game id u64 (random; the packer splits train/val by game so
#           whole games land on one side)
#   56..59  nodes used for that move's search u32 (diagnostics)
#   60..63  reserved, zero
#
# Recording rules (from docs/plans/2026_10_27_BEAT_GLAURUNG_WYLD_STASH.md):
# skip positions where the side to move is in check, where the best move is
# a capture or promotion, or where the score is a mate score. Adjudicate a
# win at |score| > 2500 for 4 straight plies and a draw at |score| < 10 for
# 10 straight plies after move 40. Games whose position after the random
# plies scores outside ±400 are discarded before play starts.
#
# Worker threads are bare Threads (no execution context): no Crystal IO in
# them, only LibC file calls and Raw.write_stdout. All directory scanning
# happens on the main thread.

module Experion
  module GenDataV5
    extend self
    include Moves

    REC_BYTES    = 64
    MAX_GAMEDITS = 240 # per-game record staging cap (the ply cap keeps this safe)

    RES_BLACK = 0 # stored as a byte in record offset 41
    RES_DRAW  = 1
    RES_WHITE = 2

    class Config
      property nodes = 5000u64
      property nodes_big = 10000u64
      property sample_pct = 20
      property open_plies = 8
      property discard_cp = 400
      property max_plies = 240
      property random_move_pct = 10
      property min_record_ply = 12
      property win_cp = 2500
      property win_plies = 4
      property draw_cp = 10
      property draw_plies = 10
      property draw_after_fullmove = 40
      property max_part_bytes = 128i64 * 1024 * 1024
      property openings = [] of String

      def self.load : Config
        c = Config.new
        if v = ENV["EXPERION_V5_NODES"]?
          c.nodes = v.to_u64?.not_nil!
        end
        if v = ENV["EXPERION_V5_NODES_BIG"]?
          c.nodes_big = v.to_u64?.not_nil!
        end
        if v = ENV["EXPERION_V5_SAMPLE_PCT"]?
          c.sample_pct = v.to_i.clamp(0, 100)
        end
        if v = ENV["EXPERION_V5_OPEN_PLIES"]?
          c.open_plies = v.to_i.clamp(0, 24)
        end
        if v = ENV["EXPERION_V5_DISCARD_CP"]?
          c.discard_cp = v.to_i.clamp(50, 10000)
        end
        if v = ENV["EXPERION_V5_MAXPLY"]?
          c.max_plies = v.to_i.clamp(40, 380)
        end
        if v = ENV["EXPERION_V5_RANDOM_PCT"]?
          c.random_move_pct = v.to_i.clamp(0, 100)
        end
        if op = ENV["EXPERION_OPENINGS"]?
          File.each_line(op) do |line|
            fen = line.strip
            c.openings << fen unless fen.empty? || fen.starts_with?('#')
          end
        end
        c
      end
    end

    def run(target : Int64, out_dir : String, threads : Int32) : Nil
      threads = threads.clamp(1, 16)
      cfg = Config.load
      Dir.mkdir_p(out_dir)

      # Resume support: count each worker's existing records and truncate any
      # ragged tail from an interrupted run so appends stay record-aligned.
      state = Array({Int64, Int32, Int64}).new(threads) { |w| scan_worker_parts(out_dir, w) }
      total_existing = state.sum { |t| t[0] }
      if total_existing >= target
        puts "gendata-v5: target #{target} already reached (#{total_existing} records in #{out_dir}); nothing to do"
        return
      end
      remaining = target - total_existing
      puts "gendata-v5: resume: #{total_existing} existing records; generating #{remaining} more, #{threads} workers"
      puts "gendata-v5: nodes=#{cfg.nodes}/#{cfg.nodes_big} sample=#{cfg.sample_pct}% open_plies=#{cfg.open_plies} discard=±#{cfg.discard_cp}"

      per = remaining // threads
      extra = remaining % threads
      t0 = Time.instant
      workers = Array(Thread).new(threads - 1)
      (1...threads).each do |i|
        quota = per + (i < extra ? 1 : 0)
        workers << Thread.new do
          v5_worker(quota, out_dir, i, state[i][1], state[i][2], cfg, i + 1)
        end
      end
      v5_worker(per + (0 < extra ? 1 : 0), out_dir, 0, state[0][1], state[0][2], cfg, 1)
      workers.each(&.join)

      total = 0i64
      threads.times { |w| total += scan_worker_parts(out_dir, w)[0] }
      elapsed = (Time.instant - t0).total_seconds
      File.open(File.join(out_dir, "manifest.txt"), "w") do |f|
        f.puts "records_total=#{total}"
        f.puts "records_new=#{total - total_existing}"
        f.puts "threads=#{threads}"
        f.puts "nodes=#{cfg.nodes} nodes_big=#{cfg.nodes_big} sample_pct=#{cfg.sample_pct}"
        f.puts "open_plies=#{cfg.open_plies} discard_cp=#{cfg.discard_cp} maxply=#{cfg.max_plies}"
      end
      printf("gendata-v5: done. %d records total (+%d) in %.1fs (%.1f pos/s)\n",
        total, total - total_existing, elapsed, (total - total_existing) / Math.max(elapsed, 0.001))
    end

    # Part-file names for worker w: the live file is part_w{w}.bin, rotated
    # files are part_w{w}.{seq}.bin. Returns {record_count, rotated_count,
    # live_file_bytes} after truncating any incomplete trailing record.
    private def scan_worker_parts(out_dir : String, w : Int32) : {Int64, Int32, Int64}
      total = 0i64
      rotated = 0
      live_bytes = 0i64
      Dir.each_child(out_dir) do |name|
        next unless name.starts_with?("part_w#{w}.") && name.ends_with?(".bin")
        path = File.join(out_dir, name)
        size = File.size(path)
        keep = (size // REC_BYTES) * REC_BYTES
        if keep != size
          File.open(path, "a") { |f| f.truncate(keep) }
        end
        if name == "part_w#{w}.bin"
          live_bytes = keep
        else
          rotated += 1
        end
        total += keep // REC_BYTES
      end
      {total, rotated, live_bytes}
    end

    private def v5_worker(quota : Int64, out_dir : String, w : Int32, rotated : Int32,
                          live_bytes : Int64, cfg : Config, seed : Int32) : Nil
      # Mix in existing record bytes: a resumed run gets a fresh RNG stream
      # instead of replaying the previous run's games (dedup would eat the
      # duplicates, but generating them costs search time).
      rng = Random.new((0x51A7 &+ seed.to_i64! &* 104729 &+ (live_bytes &* 7919i64)).to_u64!)
      s = Searcher.new(TT.new(20))
      s.verbose = false
      movebuf = Pointer(UInt16).malloc(MAX_MOVES)
      staging = Pointer(UInt8).malloc(MAX_GAMEDITS * REC_BYTES)

      live_path = File.join(out_dir, "part_w#{w}.bin").check_no_null_byte
      fd = LibC.open(live_path, LibC::O_WRONLY | LibC::O_CREAT | LibC::O_APPEND, 0o644)
      raise "open #{live_path} failed" if fd < 0
      seq = rotated # continue numbering so resumed runs never clobber rotated files
      cur_bytes = live_bytes

      emitted = 0i64
      games = 0i64
      t0 = Time.instant

      while emitted < quota
        games += 1
        if (games & 63) == 0
          rate = emitted / Math.max((Time.instant - t0).total_seconds, 0.001)
          Raw.write_stdout("v5 w#{w}: #{emitted}/#{quota} pos  #{games} games  #{rate.round(1)} pos/s\n")
        end

        s.new_game
        game_id = rng.next_u
        pos = Position.startpos
        hashes = [] of UInt64
        if !cfg.openings.empty?
          fen = cfg.openings[rng.rand(cfg.openings.size)]
          pos = begin
            Position.new(fen)
          rescue
            Position.startpos
          end
        end

        # Random opening plies for diversity (plan: 8 plies).
        cfg.open_plies.times do
          cnt = pos.generate(movebuf)
          break if cnt.zero?
          m = movebuf[rng.rand(cnt)]
          hashes << pos.hash
          child = pos
          child.make_move(m)
          pos = child
        end

        cnt = pos.generate(movebuf)
        next if cnt.zero? # random plies walked into mate/stalemate: drop the game

        # Filter search: discard games whose opening position is already
        # decided. This search doubles as the first game move's search.
        cur_mv, cur_score, cur_nodes = search_pos(s, pos, hashes, cfg.nodes)
        next if cur_mv == Moves::MOVE_NONE
        if stm_white_pov(pos, cur_score).abs > cfg.discard_cp
          next
        end

        recs = 0
        result = -1 # -1 undecided
        win_run = 0
        neg_run = 0
        draw_run = 0
        ply = 0

        loop do
          break if ply >= cfg.max_plies

          sw = stm_white_pov(pos, cur_score)

          # Adjudication counters, kept in white POV so a "run" means one side
          # keeps winning.
          if sw > cfg.win_cp
            win_run += 1
            neg_run = 0
            result = RES_WHITE if win_run >= cfg.win_plies
          elsif sw < -cfg.win_cp
            neg_run += 1
            win_run = 0
            result = RES_BLACK if neg_run >= cfg.win_plies
          else
            win_run = 0
            neg_run = 0
          end
          if pos.fullmove >= cfg.draw_after_fullmove && sw.abs < cfg.draw_cp
            draw_run += 1
            result = RES_DRAW if draw_run >= cfg.draw_plies
          else
            draw_run = 0
          end

          if result == -1 && recs < MAX_GAMEDITS &&
               ply >= cfg.min_record_ply && !pos.in_check? &&
               cur_score.abs <= Eval::MATE_IN_MAX &&
               !capture_or_promo?(pos, cur_mv)
            write_record(staging + recs * REC_BYTES, pos, sw, ply, s.last_completed_depth, cur_nodes, game_id)
            recs += 1
          end

          break if result != -1

          # Opening diversity: sometimes deviate instead of playing the search move.
          if ply < 10 && cnt > 1 && rng.rand(100) < cfg.random_move_pct
            cur_mv = movebuf[rng.rand(cnt)]
          end

          child = pos
          child.make_move(cur_mv)
          hashes << pos.hash
          pos = child
          ply += 1

          cnt = pos.generate(movebuf)
          if cnt.zero?
            result = pos.in_check? ? (pos.stm == BLACK.to_u8! ? RES_WHITE : RES_BLACK) : RES_DRAW
            break
          end
          if pos.halfmove >= 100 || Eval.insufficient_material?(pos)
            result = RES_DRAW
            break
          end

          budget = rng.rand(100) < cfg.sample_pct ? cfg.nodes_big : cfg.nodes
          cur_mv, cur_score, cur_nodes = search_pos(s, pos, hashes, budget)
          break if cur_mv == Moves::MOVE_NONE
        end

        if result == -1
          # Ply cap reached with no verdict: record it as a draw.
          result = RES_DRAW
        end

        # Patch the final result into every record of this game, then flush.
        r = staging
        recs.times do
          r[41] = result.to_u8!
          r += REC_BYTES
        end
        bytes = recs * REC_BYTES
        if bytes > 0
          LibC.write(fd, staging.as(Void*), bytes)
          cur_bytes += bytes
          emitted += recs
          if cur_bytes >= cfg.max_part_bytes
            # Rotate: rename the full live file out of the way and start fresh.
            LibC.close(fd)
            rot = File.join(out_dir, "part_w#{w}.#{seq + 1}.bin").check_no_null_byte
            LibC.rename(live_path, rot)
            seq += 1
            fd = LibC.open(live_path, LibC::O_WRONLY | LibC::O_CREAT | LibC::O_TRUNC, 0o644)
            raise "reopen #{live_path} failed" if fd < 0
            cur_bytes = 0
          end
        end
      end
      LibC.close(fd)
      elapsed = (Time.instant - t0).total_seconds
      Raw.write_stdout("v5 w#{w}: done #{emitted} records, #{games} games, #{elapsed.round(1)}s\n")
    end

    private def search_pos(s : Searcher, pos : Position, hashes : Array(UInt64), nodes : UInt64) : {UInt16, Int32, UInt64}
      limits = Limits.new
      limits.nodes_max = nodes
      mv = begin
        s.think(pos, hashes, limits)
      rescue
        Moves::MOVE_NONE
      end
      {mv, s.last_score, s.nodes}
    end

    private def stm_white_pov(pos : Position, mover_score : Int32) : Int32
      pos.stm == WHITE.to_u8! ? mover_score : -mover_score
    end

    private def capture_or_promo?(pos : Position, m : UInt16) : Bool
      return true if mv_promo_type(m) != 0
      from = mv_from(m)
      to = mv_to(m)
      return true if pos.piece_at(to) != NO_PIECE
      # en passant: a pawn diagonal move onto an empty square
      pos.piece_at(from).to_i % 6 == PAWN && ((from ^ to) & 7) != 0 && pos.piece_at(to) == NO_PIECE
    end

    # Board packing only (used by the `packboard` CLI contract check and by
    # write_record). Byte j: low nibble = square 2j, high nibble = square 2j+1,
    # matching merge_v5.py / pack_v5.py / train_v5.py exactly.
    def pack_board_into(pos : Position, p : Pointer(UInt8)) : Nil
      j = 0
      while j < 32
        lo = pos.piece_at(j * 2).to_i
        hi = pos.piece_at(j * 2 + 1).to_i
        p[j] = ((hi << 4) | lo).to_u8!
        j += 1
      end
    end

    private def write_record(p : Pointer(UInt8), pos : Position, sw : Int32, ply : Int32,
                             depth : Int32, nodes : UInt64, game_id : UInt64) : Nil
      pack_board_into(pos, p)
      put_u64(p + 32, pos.hash)
      p[40] = pos.stm
      p[41] = 0u8 # patched with the game result once the game finishes
      put_i16(p + 42, sw)
      put_u16(p + 44, ply)
      put_u16(p + 46, depth.clamp(0, 65535))
      put_u64(p + 48, game_id)
      put_u32(p + 56, nodes)
      p[60] = 0u8
      p[61] = 0u8
      p[62] = 0u8
      p[63] = 0u8
    end

    private def put_u16(p : Pointer(UInt8), v : Int) : Nil
      p[0] = (v & 0xFF).to_u8!
      p[1] = ((v >> 8) & 0xFF).to_u8!
    end

    private def put_i16(p : Pointer(UInt8), v : Int) : Nil
      put_u16(p, v & 0xFFFF)
    end

    private def put_u32(p : Pointer(UInt8), v : UInt64) : Nil
      put_u16(p, (v & 0xFFFF).to_i!)
      put_u16(p + 2, ((v >> 16) & 0xFFFF).to_i!)
    end

    private def put_u64(p : Pointer(UInt8), v : UInt64) : Nil
      put_u32(p, v & 0xFFFF_FFFFu64)
      put_u32(p + 4, (v >> 32) & 0xFFFF_FFFFu64)
    end
  end
end
