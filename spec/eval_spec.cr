require "./spec_helper"

describe Experion::Eval do
  it "gives tempo to either side to move on a symmetric board" do
    white = Experion::Position.startpos
    black = Experion::Position.new(white.to_fen.sub(" w ", " b "))
    Experion::Eval.evaluate(white).should eq(Experion::Eval::TEMPO)
    Experion::Eval.evaluate(black).should eq(Experion::Eval::TEMPO)
  end

  it "blocks white passers only with enemy pawns ahead on adjacent files" do
    pawn = 1u64 << 28 # e4
    Experion::Eval.passed_pawns(pawn, 1u64 << 44, 0).should eq(0u64) # e6
    Experion::Eval.passed_pawns(pawn, 1u64 << 43, 0).should eq(0u64) # d6
    Experion::Eval.passed_pawns(pawn, 1u64 << 12, 0).should eq(pawn) # e2
    Experion::Eval.passed_pawns(pawn, 1u64 << 42, 0).should eq(pawn) # c6
    Experion::Eval.passed_pawns(pawn, 1u64 << 27, 0).should eq(pawn) # d4
  end

  it "blocks black passers in the opposite direction" do
    pawn = 1u64 << 36 # e5
    Experion::Eval.passed_pawns(pawn, 1u64 << 20, 1).should eq(0u64)
    Experion::Eval.passed_pawns(pawn, 1u64 << 21, 1).should eq(0u64)
    Experion::Eval.passed_pawns(pawn, 1u64 << 52, 1).should eq(pawn)
    Experion::Eval.passed_pawns(pawn, 1u64 << 22, 1).should eq(pawn)
  end

  it "rewards a rook on the seventh against a king on the eighth" do
    seventh = Experion::Eval.evaluate(Experion::Position.new("4k3/R7/8/8/8/8/8/4K3 w - - 0 1"))
    sixth = Experion::Eval.evaluate(Experion::Position.new("4k3/8/R7/8/8/8/8/4K3 w - - 0 1"))
    seventh.should be > sixth
  end

  it "prefers connected passed pawns over split ones" do
    connected = Experion::Eval.evaluate(Experion::Position.new("4k3/8/8/8/8/2PP4/8/4K3 w - - 0 1"))
    split = Experion::Eval.evaluate(Experion::Position.new("4k3/8/8/8/8/2P2P2/8/4K3 w - - 0 1"))
    connected.should be > split
  end

  it "penalizes an undefended knight attacked by a rook" do
    hung = Experion::Eval.hang_overlay(Experion::Position.new("4k3/8/8/R2n4/8/8/8/4K3 w - - 0 1"))
    safe = Experion::Eval.hang_overlay(Experion::Position.new("4k3/8/8/3n4/8/8/8/4K3 w - - 0 1"))
    hung.should be > safe + 20
  end

  it "gives a middlegame bonus for a pawn storm toward the enemy king" do
    storm = Experion::Eval.evaluate(Experion::Position.new("6k1/8/8/6PP/8/8/8/4K3 w - - 0 1"))
    quiet = Experion::Eval.evaluate(Experion::Position.new("6k1/8/8/8/8/P6P/8/4K3 w - - 0 1"))
    storm.should be > quiet
  end
end
