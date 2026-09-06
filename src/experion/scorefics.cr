# Label an existing FEN;result;0 dataset with classical-eval scores (white
# POV centipawns), so the NNUE trainer gets BOTH a real WDL result signal
# and a real score-magnitude signal (see tools/nnue_train.py has_scores
# logic). Fixes the earlier WDL-only collapse where the net learned "who
# wins" but not "by how much".
#
#   bin/experion score-fics <in.txt> <out.txt>

module Experion
  module ScoreFics
    extend self

    def run(in_path : String, out_path : String) : Nil
      fout = File.open(out_path, "w")
      n = 0
      File.each_line(in_path) do |line|
        parts = line.strip.split(';')
        next if parts.size < 2
        fen = parts[0]
        result = parts[1]
        begin
          pos = Position.new(fen)
        rescue
          next
        end
        v = Eval.evaluate(pos)
        # Eval.evaluate returns side-to-move POV; convert to white POV to
        # match the training script's feature convention (white-relative).
        white_pov = pos.stm == WHITE.to_u8! ? v : -v
        fout.puts "#{fen};#{result};#{white_pov}"
        n += 1
        STDERR.puts "scored #{n}" if n % 20000 == 0
      end
      fout.close
      puts "scored #{n} positions -> #{out_path}"
    end
  end
end
