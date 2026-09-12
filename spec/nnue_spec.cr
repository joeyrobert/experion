require "./spec_helper"

# Exercise the actual search update path, including its king-move rebuild.
class Experion::Searcher
  def verify_accumulator(parent : Position, move : UInt16) : Bool
    Nnue.refresh(@accs, parent)
    child = parent
    child.make_move(move)
    push_acc(parent, move, 0, 1, child)
    expected = Pointer(Int32).malloc(Nnue.acc_row)
    Nnue.refresh(expected, child)
    Nnue.acc_row.times.all? { |i| @accs[Nnue.acc_row + i] == expected[i] }
  end
end

describe Experion::Nnue do
  it "preserves color, validates files, and updates every legal move exactly" do
    io = IO::Memory.new
    io << "ENN4"
    width = 32
    io.write_bytes(width.to_u32, IO::ByteFormat::LittleEndian)
    768.times do |feature|
      width.times do |i|
        io.write_bytes(((feature * 17 + i * 13) % 31 - 15).to_i16, IO::ByteFormat::LittleEndian)
      end
      pt = (feature % 384) // 64
      value = StaticArray[100, 320, 330, 500, 900, 0][pt]
      io.write_bytes((value * 8 * (feature < 384 ? 1 : -1)).to_i16, IO::ByteFormat::LittleEndian)
    end
    (3 * width).times { io.write_bytes(0i16, IO::ByteFormat::LittleEndian) }
    File.tempfile("experion-net", ".bin") do |file|
      file.write(io.to_slice)
      file.flush
      Experion::Nnue.load(file.path).should be_true
      Experion::Nnue.set_option(true)
      s = Experion::Searcher.new(Experion::TT.new(10))
      white_rook = Experion::Position.new("4k3/8/8/8/8/8/R7/4K3 w - - 0 1")
      black_rook = Experion::Position.new("4k3/8/8/8/8/8/r7/4K3 w - - 0 1")
      s.eval_for(white_rook).should eq(512 + Experion::Eval.hang_overlay(white_rook))
      s.eval_for(black_rook).should eq(-488 + Experion::Eval.hang_overlay(black_rook))
      [Experion::Position.startpos.to_fen,
       "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
       "4k3/P7/8/3pP3/8/8/7p/4K3 w - d6 0 1",
       "4k3/8/8/8/3pP3/8/p7/4K3 b - e3 0 1"].each do |fen|
        pos = Experion::Position.new(fen)
        moves = Pointer(UInt16).malloc(Experion::MAX_MOVES)
        pos.generate(moves).times do |i|
          s.verify_accumulator(pos, moves[i]).should be_true
        end
      end
      File.write(file.path, io.to_slice[0, 20])
      Experion::Nnue.load(file.path).should be_false
    ensure
      Experion::Nnue.set_option(false)
    end
  end
end
