# UCI protocol front-end. The main thread reads stdin; each `go` spawns a
# search thread that streams info lines and finishes with bestmove. `stop`
# raises the searcher's atomic stop flag, honored within a few thousand nodes.

module Experion
  module Uci
    private struct Clocks
      property wtime : Int64
      property btime : Int64
      property winc : Int64
      property binc : Int64
      property movestogo : Int32

      def initialize
        @wtime = 0i64
        @btime = 0i64
        @winc = 0i64
        @binc = 0i64
        @movestogo = 0
      end
    end

    def self.run : Nil
      searcher = Searcher.new
      threads = 1
      pos = Position.startpos
      game_hashes = [] of UInt64
      clocks = Clocks.new
      search_thread : Thread? = nil

      STDIN.each_line do |line|
        tokens = line.strip.split
        next if tokens.empty?
        cmd = tokens[0]

        case cmd
        when "uci"
          puts "id name Experion #{VERSION}"
          puts "id author Joey Robert"
          puts "option name Hash type spin default 32 min 1 max 4096"
          puts "option name Threads type spin default 1 min 1 max 8"
          puts "option name Use NNUE type check default #{Nnue.enabled? ? "true" : "false"}"
          puts "option name EvalBlend type spin default #{Nnue.blend} min 0 max 100"
          puts "uciok"
          STDOUT.flush
        when "isready"
          puts "readyok"
          STDOUT.flush
        when "setoption"
          name_i = tokens.index("name")
          value_i = tokens.index("value")
          if name_i && value_i && value_i > name_i
            name = tokens[(name_i + 1)...value_i].join(" ")
            value = tokens[(value_i + 1)..].join(" ")
            if name == "Hash"
              mb = value.to_i?.try(&.clamp(1, 4096)) || 32
              bits = 10
              entries = mb * (1024 * 1024) // 8
              while (1 << bits) < entries && bits < 26
                bits += 1
              end
              searcher.stop!
              search_thread.try(&.join)
              searcher = Searcher.new(TT.new(bits))
            elsif name == "Threads"
              threads = value.to_i?.try(&.clamp(1, 8)) || 1
            elsif name == "Use NNUE"
              Nnue.set_option(value != "false")
            elsif name == "EvalBlend"
              Nnue.set_blend(value.to_i?.try(&.clamp(0, 100)) || 100)
            end
          end
        when "ucinewgame"
          searcher.stop!
          search_thread.try(&.join)
          searcher.new_game
          pos = Position.startpos
          game_hashes = [] of UInt64
        when "position"
          searcher.stop!
          search_thread.try(&.join)
          pos, game_hashes = parse_position(tokens)
        when "go"
          searcher.stop!
          search_thread.try(&.join)
          limits = build_limits(tokens, pos.stm == WHITE.to_u8!, clocks)
          # The worker thread has no execution context, so it must not touch
          # Crystal IO — the searcher emits info lines via raw write, and the
          # final bestmove is written the same way.
          searcher.raw_output = true
          t = Thread.new do
            best = searcher.think_smp(pos, game_hashes, limits, threads)
            line = "bestmove #{best == Moves::MOVE_NONE ? "(none)" : Moves.mv_uci(best)}\n"
            Raw.write_stdout(line)
          end
          search_thread = t
        when "setfen", "fen"
          # convenience: set position directly by FEN
          searcher.stop!
          search_thread.try(&.join)
          fen = tokens[1..].join(" ")
          begin
            pos = Position.new(fen)
            game_hashes = [] of UInt64
          rescue e
            STDERR.puts "info string bad fen: #{e.message}"
          end
        when "perft"
          # synchronous perft from the current position: perft <depth>
          depth = tokens[1]?.try(&.to_i?) || 4
          t = Time.instant
          nodes = Perft.run(pos, depth.clamp(1, MAX_PLY - 8))
          dt = Time.instant - t
          puts "perft(#{depth}) = #{nodes} (#{dt.total_milliseconds.round(1)}ms)"
          STDOUT.flush
        when "divide"
          depth = tokens[1]?.try(&.to_i?) || 1
          Perft.divide(pos, depth.clamp(1, MAX_PLY - 8))
          STDOUT.flush
        when "eval"
          # the eval command uses the same blend logic as the search
          v = searcher.eval_for(pos)
          puts "info string static eval #{v} cp"
          STDOUT.flush
        when "stop"
          searcher.stop!
        when "ponderhit"
          # pondering not implemented yet; no-op
        when "quit"
          searcher.stop!
          search_thread.try(&.join)
          return
        end
      end

      searcher.stop!
      search_thread.try(&.join)
    end

    private def self.parse_position(tokens : Array(String)) : {Position, Array(UInt64)}
      pos = Position.startpos
      hashes = [] of UInt64

      if tokens.size >= 2 && tokens[1] == "fen"
        fen_end = tokens.index("moves") || tokens.size
        fen = tokens[2...fen_end].join(" ")
        begin
          pos = Position.new(fen)
        rescue e
          STDERR.puts "info string bad fen: #{e.message}"
        end
      end

      moves_i = tokens.index("moves")
      if moves_i
        tokens[(moves_i + 1)..].each do |u|
          m = pos.find_legal_uci(u)
          if m.nil?
            STDERR.puts "info string illegal move #{u}"
            break
          end
          child = pos
          child.make_move(m.not_nil!)
          hashes << pos.hash # hash of position BEFORE the move
          pos = child
        end
      end

      {pos, hashes}
    end

    private def self.build_limits(tokens : Array(String), white_to_move : Bool, clocks : Clocks) : Limits
      limits = Limits.new
      explicit_time = false

      i = 1
      while i < tokens.size
        case tokens[i]
        when "depth"
          d = tokens[i + 1]?.try(&.to_i?) || 0
          limits.max_depth = d.clamp(1, MAX_PLY - 8) if d > 0
          i += 1
        when "movetime"
          ms = (tokens[i + 1]?.try(&.to_i?) || 0).to_i64!
          limits.soft_ms = ms
          limits.hard_ms = ms
          explicit_time = true
          i += 1
        when "wtime"
          clocks.wtime = (tokens[i + 1]?.try(&.to_i?) || 0).to_i64!
          i += 1
        when "btime"
          clocks.btime = (tokens[i + 1]?.try(&.to_i?) || 0).to_i64!
          i += 1
        when "winc"
          clocks.winc = (tokens[i + 1]?.try(&.to_i?) || 0).to_i64!
          i += 1
        when "binc"
          clocks.binc = (tokens[i + 1]?.try(&.to_i?) || 0).to_i64!
          i += 1
        when "movestogo"
          clocks.movestogo = tokens[i + 1]?.try(&.to_i?) || 0
          i += 1
        when "nodes"
          n = tokens[i + 1]?.try(&.to_i?) || 0
          limits.nodes_max = n.to_u64! if n > 0
          i += 1
        when "infinite"
          limits.infinite = true
        when "ponder"
          # treated as normal search
        end
        i += 1
      end

      unless explicit_time || limits.infinite || limits.nodes_max != 0 ||
             limits.max_depth != MAX_PLY - 8
        my_time = white_to_move ? clocks.wtime : clocks.btime
        my_inc = white_to_move ? clocks.winc : clocks.binc
        if my_time > 0
          alloc = if clocks.movestogo > 0
                    my_time // (clocks.movestogo + 1)
                  else
                    my_time // 20 + my_inc * 3 // 4
                  end
          alloc = alloc.clamp(10i64, my_time * 3 // 4)
          limits.soft_ms = alloc
          limits.hard_ms = Math.min(alloc * 5, my_time * 3 // 4)
        else
          limits.infinite = true
        end
      end

      limits
    end
  end
end
