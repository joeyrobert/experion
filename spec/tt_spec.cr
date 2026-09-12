require "./spec_helper"

describe Experion::TT do
  it "does not report an empty entry as a hit when the verification bits are zero" do
    Experion::TT.new(10).probe(42u64)[0].should be_false
  end

  it "round trips packed entries and positive and negative mate distances" do
    tt = Experion::TT.new(10)
    key = 0xABCD123456780042u64
    tt.store(key, 42u16, -512, 12, Experion::TT::FLAG_LOWER)
    tt.probe(key).should eq({true, 42u16, -512, 12, Experion::TT::FLAG_LOWER})
    [29990, -29990, 321, -321].each do |score|
      tt.score_from_tt(tt.score_to_tt(score, 7), 7).should eq(score)
    end
  end
end

describe Experion::Position do
  it "predicts the child hash without making the move" do
    fens = [
      Experion::Position.startpos.to_fen,
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
      "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
      "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    ]
    buf = Pointer(UInt16).malloc(256)
    fens.each do |fen|
      pos = Experion::Position.new(fen)
      n = pos.generate(buf)
      i = 0
      while i < n
        m = buf[i]
        predicted = pos.hash_after(m)
        child = pos
        child.make_move(m)
        unless child.hash == predicted
          raise "hash_after mismatch on #{Experion::Moves.mv_uci(m)} from #{fen}"
        end
        i += 1
      end
    end
  end
end
