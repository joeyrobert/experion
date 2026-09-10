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
