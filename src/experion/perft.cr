# Perft driver. Because move generation is fully legal, depth-1 nodes are
# bulk-counted straight from the generator's return value.

module Experion
  module Perft
    extend self

    def count(pos : Position, depth : Int32, buf : Pointer(UInt16)) : UInt64
      n = pos.generate(buf)
      return n.to_u64! if depth <= 1

      total = 0u64
      i = 0
      while i < n
        child = pos
        child.make_move(buf[i], false)
        total += count(child, depth - 1, buf + MAX_MOVES)
        i += 1
      end
      total
    end

    # Convenience wrapper allocating the move buffer.
    def run(pos : Position, depth : Int32) : UInt64
      raise "depth too deep" if depth >= MAX_PLY - 2
      buf = Pointer(UInt16).malloc(MAX_MOVES * (depth + 1))
      count(pos, depth, buf)
    end

    # Per-root-move breakdown for debugging.
    def divide(pos : Position, depth : Int32) : Nil
      buf = Pointer(UInt16).malloc(MAX_MOVES * (depth + 1))
      n = pos.generate(buf)
      total = 0u64
      t0 = Time.instant
      entries = Array(Tuple(String, UInt64)).new(n)
      i = 0
      while i < n
        child = pos
        child.make_move(buf[i], false)
        c = depth <= 1 ? 1u64 : count(child, depth - 1, buf + MAX_MOVES)
        entries << {Moves.mv_uci(buf[i]), c}
        total += c
        i += 1
      end
      dt = Time.instant - t0
      ms = dt.total_milliseconds
      nps = ms > 0 ? total * 1000 // ms : total
      entries.sort_by!(&.[0])
      entries.each do |m, c|
        puts "#{m}: #{c}"
      end
      puts "total: #{total} (#{ms.round(1)}ms, #{nps} nps)"
    end

    # Cross-check: non-bulk perft that makes every single move (validates the
    # bulk-counting assumption itself).
    def count_no_bulk(pos : Position, depth : Int32, buf : Pointer(UInt16)) : UInt64
      n = pos.generate(buf)
      return n.to_u64! if depth <= 1
      total = 0u64
      i = 0
      while i < n
        child = pos
        child.make_move(buf[i], false)
        if depth == 2
          buf2 = buf + MAX_MOVES
          total += child.generate(buf2).to_u64!
        else
          total += count_no_bulk(child, depth - 1, buf + MAX_MOVES)
        end
        i += 1
      end
      total
    end
  end
end
