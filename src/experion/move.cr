# Move encoding/decoding helpers.
#
# Moves pack into UInt16:
#   bits  0..5  from square
#   bits  6..11 to square
#   bits 12..14 promotion piece type (0 none, 1=N 2=B 3=R 4=Q)
#
# No explicit EP/castling flag bits fit, and none are needed: both are
# detected structurally in make_move().
#   castling: the king moves horizontally by exactly two files
#   en passant: a pawn moves diagonally onto an empty square
#
# `Moves` is extended for standalone use and included into Position so the
# encoders resolve statically inside the generator.

module Experion
  module Moves
    extend self

    MOVE_NONE = 0u16

    @[AlwaysInline]
    def move(from : Int, to : Int) : UInt16
      (from | (to << 6)).to_u16!
    end

    @[AlwaysInline]
    def move_ep(from : Int, to : Int) : UInt16
      move(from, to)
    end

    @[AlwaysInline]
    def move_castle(from : Int, to : Int) : UInt16
      move(from, to)
    end

    @[AlwaysInline]
    def move_promo(from : Int, to : Int, ptype : Int) : UInt16
      (from | (to << 6)).to_u16! | (ptype.to_u16! << 12)
    end

    @[AlwaysInline]
    def mv_from(m : UInt16) : Int32
      (m & 63).to_i!
    end

    @[AlwaysInline]
    def mv_to(m : UInt16) : Int32
      ((m >> 6) & 63).to_i!
    end

    # 0 = no promotion, else piece type 1..4
    @[AlwaysInline]
    def mv_promo_type(m : UInt16) : Int32
      ((m >> 12) & 7).to_i!
    end

    def mv_uci(m : UInt16) : String
      String.build do |s|
        s << FILES[mv_from(m) & 7] << RANKS[mv_from(m) >> 3]
        s << FILES[mv_to(m) & 7] << RANKS[mv_to(m) >> 3]
        case mv_promo_type(m)
        when 1 then s << 'n'
        when 2 then s << 'b'
        when 3 then s << 'r'
        when 4 then s << 'q'
        end
      end
    end

    def parse_uci_move(s : String) : UInt16?
      return nil unless s.size.in?(4, 5)
      f = FILES.index(s[0])
      fr = RANKS.index(s[1])
      t = FILES.index(s[2])
      tr = RANKS.index(s[3])
      return nil if f.nil? || fr.nil? || t.nil? || tr.nil?
      from = fr * 8 + f
      to = tr * 8 + t
      if s.size == 5
        pt = case s[4].downcase
             when 'n' then KNIGHT
             when 'b' then BISHOP
             when 'r' then ROOK
             when 'q' then QUEEN
             else          return nil
             end
        move_promo(from, to, pt)
      else
        move(from, to)
      end
    end
  end
end
