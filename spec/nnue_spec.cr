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
      s.eval_for(white_rook).should eq(512)
      s.eval_for(black_rook).should eq(-488)
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

describe "ENN5" do
  it "loads, evaluates from the side to move, and keeps incremental accumulators exact" do
    h = 32
    io = IO::Memory.new
    io << "ENN5"
    [h, 8, 8, 1].each { |v| io.write_bytes(v.to_u32, IO::ByteFormat::LittleEndian) }
    rng = Random.new(7)
    (768 * 8 * h).times { io.write_bytes(rng.rand(-40..40).to_i16, IO::ByteFormat::LittleEndian) }
    h.times { io.write_bytes(rng.rand(-20..20).to_i16, IO::ByteFormat::LittleEndian) }
    (8 * 2 * h).times { io.write_bytes(rng.rand(-30..30).to_i16, IO::ByteFormat::LittleEndian) }
    8.times { io.write_bytes(0i32, IO::ByteFormat::LittleEndian) }
    [100, 320, 330, 500, 900].each { |v| io.write_bytes(v.to_i16, IO::ByteFormat::LittleEndian) }
    File.tempfile("experion-enn5", ".bin") do |file|
      file.write(io.to_slice)
      file.flush
      Experion::Nnue.load(file.path).should be_true
      Experion::Nnue.v5?.should be_true
      Experion::Nnue.set_option(true)
      s = Experion::Searcher.new(Experion::TT.new(10))
      # material lane: a bare extra rook is worth its 500 to the side that owns it
      up = Experion::Position.new("4k3/8/8/8/8/8/R7/4K3 w - - 0 1")
      down = Experion::Position.new("4k3/8/8/8/8/8/r7/4K3 b - - 0 1")
      (s.raw_nnue(up) - s.raw_nnue(Experion::Position.new("4k3/8/8/8/8/8/1R6/4K3 w - - 0 1"))).abs.should be < 2000
      s.raw_nnue(up).should be > s.raw_nnue(Experion::Position.new("4k3/8/8/8/8/8/8/4K3 w - - 0 1")) - 1000
      down.stm.should eq(Experion::BLACK.to_u8!)
      [Experion::Position.startpos.to_fen,
       "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
       "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
       "4k3/P7/8/3pP3/8/8/7p/4K3 w - d6 0 1",
       "4k3/8/8/8/3pP3/8/p7/4K3 b - e3 0 1",
       "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
       "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"].each do |fen|
        pos = Experion::Position.new(fen)
        moves = Pointer(UInt16).malloc(Experion::MAX_MOVES)
        pos.generate(moves).times do |i|
          s.verify_accumulator(pos, moves[i]).should be_true
        end
      end
    ensure
      Experion::Nnue.set_option(false)
    end
  end
end
