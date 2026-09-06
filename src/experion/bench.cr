# Benchmarks: raw legal move generation throughput and bulk perft speed.

module Experion
  module Bench
    extend self

    # Diverse positions: middlegame, endgame, checks, pins, promotions, EP.
    FENS = [
      STARTPOS_FEN,
      "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
      "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
      "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
      "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
      "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
      "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
      "8/5bk1/8/2Pp4/8/1K6/8/8 w - d6 0 1",
      "8/8/1k6/4b3/8/8/5PPP/6K1 w - - 0 1",
      "6k1/5p2/1p5p/p4Np1/5P2/8/PP3K2/8 w - - 0 1",
      "8/P1PPPP1P/8/1k6/8/4K3/8/8 w - - 0 1",
      "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
      "1k1r4/pp1b1R2/3q2pp/4p3/2B5/4Q3/PPP2B2/2K5 b - - 0 1",
      "6k1/6pp/8/8/8/8/5PPP/R5K1 w - - 0 1",
      "4k3/8/8/8/8/8/8/4K2R w K - 0 1",
      "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
      "8/2k1p3/3pP3/3P2K1/8/8/8/8 w - - 0 1",
      "8/8/2k5/5q2/5n2/8/5K2/8 b - - 0 1",
      "n1n5/PPPk4/8/8/8/8/4Kppp/5N1N w - - 0 1",
      "8/5k2/8/8/8/8/2K5/8 w - - 0 1",
    ]

    def run(mode : Int32) : Nil
      case mode
      when 1
        bench_gen
      when 2
        bench_perft
      else
        bench_gen
        bench_perft
      end
    end

    def bench_gen : Nil
      positions = FENS.map { |f| Position.new(f) }
      buf = Pointer(UInt16).malloc(MAX_MOVES)

      # warmup
      2000.times do
        positions.each do |pos|
          pos.generate(buf)
        end
      end

      total = 0u64
      t0 = Time.instant
      iterations = 0
      while (Time.instant - t0) < 2.seconds
        1000.times do
          positions.each do |pos|
            total += pos.generate(buf).to_u64!
          end
        end
        iterations += 1000
      end
      dt = Time.instant - t0
      printf("movegen: %d moves in %.2fs (%.1f M moves/sec generated, %d iterations)\n",
        total, dt.total_seconds, total / dt.total_microseconds, iterations)
    end

    def bench_perft : Nil
      total = 0u64
      t0 = Time.instant
      FENS.each do |fen|
        pos = Position.new(fen)
        3.downto(1) do |d|
          total += Perft.run(pos, d)
        end
      end
      dt = Time.instant - t0
      printf("perft: %d nodes in %.2fs (%.1f Mnps, bulk counting)\n",
        total, dt.total_seconds, total / dt.total_microseconds)
    end
  end
end
