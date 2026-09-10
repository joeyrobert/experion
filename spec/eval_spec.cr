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
end
