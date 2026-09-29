# EPD test-suite runner: solves positions with a fixed time per move and
# compares the played move against the `bm` (best move) field (SAN form).
#
#   experion epdtest suites/wac.epd 200        # 200ms per position

module Experion
  module EpdTest
    extend self

    def run(path : String, movetime_ms : Int64, max_positions : Int32) : Nil
      lines = File.read_lines(path)
      solved = 0
      total = 0
      searcher = Searcher.new(TT.new(20))
      searcher.verbose = false

      lines.each do |line|
        break if max_positions > 0 && total >= max_positions
        line = line.strip
        next if line.empty?
        next unless line.includes?("bm ")

        fen_part = line.split("bm ")[0].strip
        bm_raw = line.split("bm ")[1]
        best_moves = bm_raw.split(";")[0].split(/[,\s]+/).map(&.strip.gsub(/[+#!?]/, "")).reject(&.empty?)

        pos = begin
          Position.new(fen_part)
        rescue
          next
        end

        limits = Limits.new
        limits.soft_ms = movetime_ms
        limits.hard_ms = movetime_ms * 4

        best = searcher.think(pos, [] of UInt64, limits)
        played_san = San.move_san(pos, best).gsub(/[+#!?]/, "")
        played_uci = Moves.mv_uci(best)

        ok = best_moves.includes?(played_san) || best_moves.includes?(played_uci)

        total += 1
        solved += 1 if ok
        puts "#{ok ? "." : "x"} #{total} #{played_san} [#{played_uci}] want: #{best_moves.join(",")}" unless ok
        STDOUT.flush
      end

      pct = total > 0 ? solved * 100 // total : 0
      puts "solved #{solved}/#{total} (#{pct}%)"
    end
  end
end
