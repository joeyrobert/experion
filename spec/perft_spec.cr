require "./spec_helper"

# Canonical reference positions (chessprogramming.org "Perft Results")
STANDARD_SIX = [
  {fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth: 5, count: 4865609u64},
  {fen: "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", depth: 4, count: 4085603u64},
  {fen: "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", depth: 5, count: 674624u64},
  {fen: "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", depth: 4, count: 422333u64},
  {fen: "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", depth: 4, count: 2103487u64},
  {fen: "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", depth: 4, count: 3894594u64},
]

describe Experion::Perft do
  before_all do
    Experion.init_engine
  end

  describe "standard positions" do
    STANDARD_SIX.each_with_index do |tc, i|
      it "position #{i + 1} at depth #{tc[:depth]} == #{tc[:count]}" do
        pos = Experion::Position.new(tc[:fen])
        Experion::Perft.run(pos, tc[:depth]).should eq(tc[:count])
      end
    end
  end

  describe "bulk vs no-bulk cross-check" do
    # Validates the bulk-counting assumption itself: every move must be legal
    # without needing make/test verification.
    [
      {"r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3},
      {"8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4},
      {"r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3},
    ].each do |fen, depth|
      it "matches non-bulk counting for #{fen}" do
        pos = Experion::Position.new(fen)
        buf = Pointer(UInt16).malloc(Experion::MAX_MOVES * (depth + 1))
        bulk = Experion::Perft.count(pos, depth, buf)
        nobulk = Experion::Perft.count_no_bulk(pos, depth, buf)
        bulk.should eq(nobulk)
      end
    end
  end

  describe "perftsuite fixture" do
    lines = File.read("spec/fixtures/perftsuite.epd").split("\n")

    lines.each do |line|
      next if line.strip.empty?
      parts = line.split(';')
      fen = parts[0].strip

      parts[1..].each do |entry|
        entry = entry.strip
        next if entry.empty?
        dparts = entry.split
        next unless dparts.size >= 2 && dparts[0].starts_with?("D")
        depth = dparts[0][1..].to_i
        count = dparts[1].to_u64

        it "#{fen} D#{depth} == #{count}" do
          pos = Experion::Position.new(fen)
          Experion::Perft.run(pos, depth).should eq(count)
        end
      end
    end
  end
end
