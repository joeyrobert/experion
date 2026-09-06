# Precomputed lookup tables: magic bitboards for sliders, plus static attack
# tables for leapers, and between/line masks used by legal move generation.
#
# All hot lookups go through raw pointers (no bounds checks) and are marked
# AlwaysInline so LLVM folds them into the caller.

module Experion
  module Tables
    extend self

    # --- Raw table storage ----------------------------------------------------

    ROOK_MASK   = Pointer(UInt64).malloc(64)
    ROOK_MAGIC  = Pointer(UInt64).malloc(64)
    ROOK_SHIFT  = Pointer(UInt8).malloc(64)
    ROOK_OFFSET = Pointer(Int32).malloc(64)
    ROOK_ATTACKS  = Pointer(UInt64).malloc(102400)

    BISHOP_MASK   = Pointer(UInt64).malloc(64)
    BISHOP_MAGIC  = Pointer(UInt64).malloc(64)
    BISHOP_SHIFT  = Pointer(UInt8).malloc(64)
    BISHOP_OFFSET = Pointer(Int32).malloc(64)
    BISHOP_ATTACKS = Pointer(UInt64).malloc(65536)

    KNIGHT_ATK = Pointer(UInt64).malloc(64)
    KING_ATK   = Pointer(UInt64).malloc(64)
    PAWN_ATK   = Pointer(UInt64).malloc(128) # [(color << 6) + square]

    BETWEEN = Pointer(UInt64).malloc(4096) # strictly-between squares, aligned pairs
    LINE    = Pointer(UInt64).malloc(4096) # full line through both squares, aligned pairs

    FILE_BB = StaticArray[
      0x0101010101010101u64, 0x0202020202020202u64, 0x0404040404040404u64, 0x0808080808080808u64,
      0x1010101010101010u64, 0x2020202020202020u64, 0x4040404040404040u64, 0x8080808080808080u64,
    ]
    RANK_BB = StaticArray[
      0x00000000000000FFu64, 0x000000000000FF00u64, 0x0000000000FF0000u64, 0x00000000FF000000u64,
      0x000000FF00000000u64, 0x0000FF0000000000u64, 0x00FF000000000000u64, 0xFF00000000000000u64,
    ]

    # Magic bitboard lookups ---------------------------------------------------

    @[AlwaysInline]
    def rook_attacks(sq : Int, occ : UInt64) : UInt64
      ROOK_ATTACKS[ROOK_OFFSET[sq] +
        (((occ & ROOK_MASK[sq]) &* ROOK_MAGIC[sq]) >> ROOK_SHIFT[sq])]
    end

    @[AlwaysInline]
    def bishop_attacks(sq : Int, occ : UInt64) : UInt64
      BISHOP_ATTACKS[BISHOP_OFFSET[sq] +
        (((occ & BISHOP_MASK[sq]) &* BISHOP_MAGIC[sq]) >> BISHOP_SHIFT[sq])]
    end

    @[AlwaysInline]
    def queen_attacks(sq : Int, occ : UInt64) : UInt64
      rook_attacks(sq, occ) | bishop_attacks(sq, occ)
    end

    @[AlwaysInline]
    def knight_attacks(sq : Int) : UInt64
      KNIGHT_ATK[sq]
    end

    @[AlwaysInline]
    def king_attacks(sq : Int) : UInt64
      KING_ATK[sq]
    end

    @[AlwaysInline]
    def pawn_attacks(color : Int, sq : Int) : UInt64
      # to_i! guards against UInt8 args (small-int shift would wrap)
      PAWN_ATK[(color.to_i! << 6) + sq]
    end

    @[AlwaysInline]
    def between(a : Int, b : Int) : UInt64
      BETWEEN[(a << 6) + b]
    end

    @[AlwaysInline]
    def line(a : Int, b : Int) : UInt64
      LINE[(a << 6) + b]
    end

    # --- Initialization ---------------------------------------------------------

    @@initialized = false

    def init : Nil
      return if @@initialized
      @@initialized = true

      init_leaper_tables
      init_between_line
      init_magics(true)
      init_magics(false)
    end

    DIRS_ALL     = [{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}]
    DIRS_KNIGHT  = [{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}]
    DIRS_ROOK    = [{1, 0}, {-1, 0}, {0, 1}, {0, -1}]
    DIRS_BISHOP  = [{1, 1}, {1, -1}, {-1, 1}, {-1, -1}]

    private def init_leaper_tables
      sq = 0
      while sq < 64
        f = sq & 7
        r = sq >> 3

        kn = 0u64
        DIRS_KNIGHT.each do |df, dr|
          nf = f + df
          nr = r + dr
          kn |= 1u64 << (nr &* 8 &+ nf) if nf.in?(0..7) && nr.in?(0..7)
        end
        KNIGHT_ATK[sq] = kn

        kg = 0u64
        DIRS_ALL.each do |df, dr|
          nf = f + df
          nr = r + dr
          kg |= 1u64 << (nr &* 8 &+ nf) if nf.in?(0..7) && nr.in?(0..7)
        end
        KING_ATK[sq] = kg

        wp = 0u64
        wp |= 1u64 << (sq + 7) if r < 7 && f > 0
        wp |= 1u64 << (sq + 9) if r < 7 && f < 7
        PAWN_ATK[(WHITE << 6) + sq] = wp

        bp = 0u64
        bp |= 1u64 << (sq - 9) if r > 0 && f > 0
        bp |= 1u64 << (sq - 7) if r > 0 && f < 7
        PAWN_ATK[(BLACK << 6) + sq] = bp

        sq += 1
      end
    end

    private def init_between_line
      i = 0
      while i < 4096
        BETWEEN[i] = 0u64
        LINE[i] = 0u64
        i += 1
      end

      a = 0
      while a < 64
        af = a & 7
        ar = a >> 3
        DIRS_ALL.each do |df, dr|
          b_f = af + df
          b_r = ar + dr
          while b_f.in?(0..7) && b_r.in?(0..7)
            b = b_r * 8 + b_f

            # full line through a and b
            lm = 0u64
            x_f, x_r = af, ar
            while x_f.in?(0..7) && x_r.in?(0..7)
              lm |= 1u64 << (x_r * 8 + x_f)
              x_f += df
              x_r += dr
            end
            x_f, x_r = af - df, ar - dr
            while x_f.in?(0..7) && x_r.in?(0..7)
              lm |= 1u64 << (x_r * 8 + x_f)
              x_f -= df
              x_r -= dr
            end
            LINE[(a << 6) + b] = lm

            # strictly between a and b
            btw = 0u64
            y_f, y_r = af + df, ar + dr
            until y_f == b_f && y_r == b_r
              btw |= 1u64 << (y_r * 8 + y_f)
              y_f += df
              y_r += dr
            end
            BETWEEN[(a << 6) + b] = btw

            b_f += df
            b_r += dr
          end
        end
        a += 1
      end
    end

    private def slow_slider_attacks(sq : Int, occ : UInt64, dirs) : UInt64
      f = sq & 7
      r = sq >> 3
      result = 0u64
      dirs.each do |df, dr|
        x_f = f + df
        x_r = r + dr
        while x_f.in?(0..7) && x_r.in?(0..7)
          s = x_r * 8 + x_f
          result |= 1u64 << s
          break if (occ >> s) & 1 != 0
          x_f += df
          x_r += dr
        end
      end
      result
    end

    private def slider_mask(sq : Int, is_rook : Bool) : UInt64
      f = sq & 7
      r = sq >> 3
      m = 0u64
      if is_rook
        (f + 1...7).each { |x| m |= 1u64 << (r * 8 + x) }         # east, excl. h-file
        (1...f).each { |x| m |= 1u64 << (r * 8 + x) }             # west, excl. a-file
        (r + 1...7).each { |y| m |= 1u64 << (y * 8 + f) }         # north, excl. rank 8
        (1...r).each { |y| m |= 1u64 << (y * 8 + f) }             # south, excl. rank 1
      else
        DIRS_BISHOP.each do |df, dr|
          x_f = f + df
          x_r = r + dr
          while x_f.in?(1..6) && x_r.in?(1..6)
            m |= 1u64 << (x_r * 8 + x_f)
            x_f += df
            x_r += dr
          end
        end
      end
      m
    end

    private def init_magics(is_rook : Bool)
      dirs = is_rook ? DIRS_ROOK : DIRS_BISHOP
      mask_p   = is_rook ? ROOK_MASK : BISHOP_MASK
      magic_p  = is_rook ? ROOK_MAGIC : BISHOP_MAGIC
      shift_p  = is_rook ? ROOK_SHIFT : BISHOP_SHIFT
      offset_p = is_rook ? ROOK_OFFSET : BISHOP_OFFSET
      table    = is_rook ? ROOK_ATTACKS : BISHOP_ATTACKS
      baked    = is_rook ? MagicConstants::ROOK_MAGICS : MagicConstants::BISHOP_MAGICS

      offset = 0
      sq = 0
      while sq < 64
        mask = slider_mask(sq, is_rook)
        mask_p[sq] = mask
        bits = mask.popcount
        shift_p[sq] = (64 - bits).to_u8

        # magic multipliers are baked in by tools/gen_magics.cr (deterministic)
        magic = baked[sq]

        # enumerate all occupancy subsets of the mask (carry-rippler)
        n = 1 << bits
        s = 0u64
        i = 0
        loop do
          table[offset + ((s &* magic) >> (64 - bits))] = slow_slider_attacks(sq, s, dirs)
          s = (s &- mask) & mask
          i += 1
          break if s.zero?
        end

        magic_p[sq] = magic
        offset_p[sq] = offset
        offset += (1 << bits)
        sq += 1
      end
    end
  end
end
