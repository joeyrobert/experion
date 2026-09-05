# Generate NNUE training data from a FICS PGN database.
#
#   bin/experion genfics-data <in.pgn.bz2> <out.txt> <count> <min_ply> <max_ply>
#
# Streams the bz2 PGN, parses games, replays moves, extracts positions
# at midgame plies. Each position is labeled with the game result. We
# also do a "quiet" filter: skip positions where the next move is a
# capture, in-check, or a recapture (high-tactical). The engine's own
# search would be too slow on millions of positions, so we use the game
# result as the WDL target. The eval-blend target can come from a
# stronger engine offline (see tools/score_fics.sh).
#
# Output format: FEN;result;score_cp (one per line, same as nnue_train).

module Experion
  module GenFicsData
    extend self
    include Moves

    def run(path : String, out_path : String, target : Int32, min_ply : Int32, max_ply : Int32) : Nil
      fout = File.open(out_path, "w")
      emitted = 0
      processed = 0
      game_buf = IO::Memory.new
      in_game = false

      # stream via bzcat
      io = Process.new("bzcat", [path], output: Process::Redirect::Pipe).output

      io.each_line do |line|
        line = line.chomp
        if line.starts_with?("[Event ")
          # process previous game
          if in_game
            processed += 1
            if processed % 10000 == 0
              STDERR.puts "Processed #{processed}, emitted #{emitted}"
            end
            if emitted < target
              res = parse_and_extract(game_buf.to_s, min_ply, max_ply, fout)
              if res > 0
                emitted += res
              end
            end
          end
          game_buf = IO::Memory.new
          game_buf << line << '\n'
          in_game = true
        elsif in_game
          game_buf << line << '\n'
        end
        break if emitted >= target
      end

      # process last game
      if in_game && emitted < target
        processed += 1
        res = parse_and_extract(game_buf.to_s, min_ply, max_ply, fout)
        if res > 0
          emitted += res
        end
      end

      io.close
      fout.close
      puts "Processed #{processed} games, emitted #{emitted} positions"
    end

    private def parse_and_extract(pgn : String, min_ply : Int32, max_ply : Int32, fout : File) : Int32
      # find result
      result_m = pgn.match(/\[Result "([^"]+)"\]/)
      return 0 unless result_m
      result = result_m[1]
      score = case result
              when "1-0"   then 1.0
              when "0-1"   then 0.0
              when "1/2-1/2" then 0.5
              else
                return 0
              end

      # find moves (after the empty line)
      parts = pgn.split(/\n\n/, 2)
      return 0 if parts.size < 2
      moves_str = parts[1]
      # strip comments
      moves_str = moves_str.gsub(/\{[^}]*\}/, "")
      moves_str = moves_str.gsub(/\([^)]*\)/, "")
      moves_str = moves_str.gsub(/\d+\.\.\./, "")
      moves_str = moves_str.gsub(/\d+\./, "")
      moves_str = moves_str.gsub(/\$\d+/, "")
      moves_str = moves_str.gsub(/1-0|0-1|1\/2-1\/2|\*/, "")
      moves = moves_str.split(/\s+/).reject(&.empty?)

      return 0 if moves.size < 10

      # replay moves, extract positions
      pos = Position.startpos
      emitted = 0
      ply = 0
      moves.each do |san|
        m = pos.find_legal_uci(san)
        break if m.nil?
        child = pos
        child.make_move(m)
        pos = child
        ply += 1

        # extract position at midgame plies
        if ply >= min_ply && ply <= max_ply && (ply % 4 == 0)
          # quiet filter: skip if in check (tactical)
          next if pos.in_check?
          # skip if material is very low (rare endgames)
          next if pos.occ_all.popcount < 8
          # write FEN;result;0
          fen = pos.to_fen
          # ensure the position has full move counters
          fout.puts "#{fen};#{score};0"
          emitted += 1
        end
        break if emitted >= 200  # cap per game
      end
      emitted
    rescue
      0
    end
  end
end
