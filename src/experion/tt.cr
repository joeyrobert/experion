# Transposition table: fixed-size array of packed 64-bit entries.
#
# Entry layout:
#   bits  0..15  move
#   bits 16..31  score (Int16; mate scores stored relative to this node)
#   bits 32..39  depth (0..255)
#   bits 40..41  flag (EXACT / LOWER / UPPER)
#   bits 42..47  age (generation counter)
#   bits 48..63  high 16 bits of the position hash (verification)
#
# Indexed by low bits of the hash. Replacement: prefer same-position deeper
# entries from the current search generation; otherwise deeper or fresher wins.

module Experion
  class TT
    FLAG_EXACT = 1u8
    FLAG_LOWER = 2u8 # beta cutoff: score is a lower bound
    FLAG_UPPER = 3u8 # alpha never raised: score is an upper bound

    @entries : Pointer(UInt64)
    @size : Int32

    getter mask, size

    def initialize(bits : Int32 = 22) # default 2^22 * 8B = 32MB
      @size = 1 << bits
      @mask = (@size - 1).to_u64!
      @entries = Pointer(UInt64).malloc(@size)
      @entries.clear(@size)
      @age = Atomic(UInt8).new(0u8)
    end

    def new_game : Nil
      @entries.clear(@size)
      @age.set(0u8)
    end

    @[AlwaysInline]
    def probe(hash : UInt64) : {Bool, UInt16, Int32, Int32, UInt8}
      e = Atomic::Ops.load(@entries + (hash & @mask), :monotonic, false)
      if e != 0 && (e >> 48).to_u16! == (hash >> 48).to_u16!
        move = (e & 0xFFFF).to_u16!
        score = ((e >> 16) & 0xFFFF).to_u16!.to_i16!.to_i32!
        depth = ((e >> 32) & 0xFF).to_i32!
        flags = ((e >> 40) & 3).to_u8!
        {true, move, score, depth, flags}
      else
        {false, Moves::MOVE_NONE, 0, 0, 0u8}
      end
    end

    # Shared across worker threads in think_smp (each searcher's own @tt is
    # the same instance) — must be a real atomic RMW. A plain UInt8 field
    # bumped from multiple threads concurrently can lose increments or hand
    # out a torn read to `store`'s replacement-policy check, both of which
    # are silent correctness bugs, not just noise.
    def bump_age : Nil
      @age.add(1u8)
    end

    def store(hash : UInt64, move : UInt16, score : Int32, depth : Int32, flags : UInt8) : Nil
      idx = hash & @mask
      old = Atomic::Ops.load(@entries + idx, :monotonic, false)
      depth = depth.clamp(0, 255)
      cur_age = @age.get.to_i32! & 0x3F

      if old != 0
        old_depth = ((old >> 32) & 0xFF).to_i32!
        old_age = ((old >> 42) & 0x3F).to_i32!
        same_key = (old >> 48).to_u16! == (hash >> 48).to_u16!

        if same_key
          # always overwrite same-position entries with a deeper one from any age;
          # shallower same-position entries in the current generation are skipped
          return if old_depth > depth && old_age == cur_age
        else
          # different position: prefer deeper OR fresher.
          # Within the same generation, keep the deeper one.
          return if old_age == cur_age && old_depth > depth
          # From an older generation: only replace if the new entry is at
          # least as deep — gives a real signal rather than letting every
          # shallow qsearch node churn the table.
          return if old_age != cur_age && old_depth >= depth && depth < 4
        end
      end

      s16 = if score > 32767i32
              32767i16
            elsif score < -32768i32
              -32768i16
            else
              score.to_i16!
            end
      entry = move.to_u64 |
              (s16.to_u16!.to_u64 << 16) |
              (depth.to_u64 << 32) |
              ((flags.to_u64 | (cur_age.to_u64 << 2)) << 40) |
              ((hash >> 48) << 48)
      Atomic::Ops.store(@entries + idx, entry, :monotonic, false)
    end

    # mate scores are stored relative to the node they were found at
    @[AlwaysInline]
    def score_to_tt(score : Int32, ply : Int32) : Int32
      if score > Eval::MATE_IN_MAX
        score + ply
      elsif score < -Eval::MATE_IN_MAX
        score - ply
      else
        score
      end
    end

    @[AlwaysInline]
    def score_from_tt(score : Int32, ply : Int32) : Int32
      if score > Eval::MATE_IN_MAX
        score - ply
      elsif score < -Eval::MATE_IN_MAX
        score + ply
      else
        score
      end
    end
  end
end
