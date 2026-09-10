require "./spec_helper"

class Experion::Searcher
  def quiescence_for_spec(pos : Position, checks : Bool = false) : Int32
    @hashes[0] = pos.hash
    @base_ply = 0
    Nnue.refresh(@accs, pos) if Nnue.enabled?
    qsearch(pos, -INF, INF, 0, Limits.new, checks)
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
end
