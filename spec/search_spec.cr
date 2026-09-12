require "./spec_helper"

class Experion::Searcher
  def quiescence_for_spec(pos : Position, checks : Bool = false) : Int32
    @hashes[0] = pos.hash
    @base_ply = 0
    Nnue.refresh(@accs, pos) if Nnue.enabled?
    qsearch(pos, -INF, INF, 0, Limits.new, checks ? 2 : 0)
  end
end

describe Experion::Searcher do
  it "shares cancellation storage between search workers" do
    stop = Experion::SearchStop.new
    one = Experion::Searcher.new(Experion::TT.new(10), stop)
    two = Experion::Searcher.new(Experion::TT.new(10), stop)
    one.stop!
    two.stopped?.should be_true
    stop.get.should be_true
  end

  it "recognizes stalemate at the quiescence horizon" do
    pos = Experion::Position.new("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
    Experion::Searcher.new(Experion::TT.new(10)).quiescence_for_spec(pos).should eq(0)
  end

  it "searches quiet checking moves at the first quiescence ply" do
    pos = Experion::Position.new("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
    Experion::Searcher.new(Experion::TT.new(10)).quiescence_for_spec(pos, true).should eq(Experion::Eval::MATE - 1)
  end

  it "recognizes the fifty-move rule inside quiescence" do
    pos = Experion::Position.new("7k/8/5KQ1/8/8/8/8/8 w - - 100 70")
    Experion::Searcher.new(Experion::TT.new(10)).quiescence_for_spec(pos).should eq(0)
  end

  it "does not play a quiet that hangs a knight to a pawn at the root" do
    pos = Experion::Position.new("4k3/8/8/3p4/8/8/4N3/4K3 w - - 0 1")
    s = Experion::Searcher.new(Experion::TT.new(12))
    s.verbose = false
    limits = Experion::Limits.new
    limits.max_depth = 6
    limits.soft_ms = 200
    limits.hard_ms = 200
    mv = s.think(pos, [] of UInt64, limits)
    Experion::Moves.mv_uci(mv).should_not eq("e2e4")
  end
end

describe Experion::See do
  it "scores a quiet move onto a hanging square as losing" do
    pos = Experion::Position.new("4k3/8/8/3p4/8/8/4N3/4K3 w - - 0 1")
    m = Experion::Moves.move(12, 28) # Ne2-e4, into d5's capture
    Experion::See.see(pos, m).should be < 0
  end

  it "scores a hanging pawn push as at least a pawn loss" do
    pos = Experion::Position.new("4k3/8/8/3p4/8/8/4P3/4K3 w - - 0 1")
    m = Experion::Moves.move(12, 28) # e2-e4, into d5's capture
    Experion::See.see(pos, m).should be <= -100
  end

  it "scores a quiet move onto a safe square as non-negative" do
    pos = Experion::Position.new("4k3/8/8/8/8/8/4N3/4K3 w - - 0 1")
    m = Experion::Moves.move(12, 28)
    Experion::See.see(pos, m).should be >= 0
  end
end
