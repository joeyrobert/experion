# SAN generation for legal moves (used by EPD test matching and debug output).

module Experion
  module San
    extend self
    include Moves

    def move_san(pos : Position, m : UInt16) : String
    from = mv_from(m)
    to = mv_to(m)
    promo = mv_promo_type(m)
    pc = pos.piece_at(from).to_i
    ptype = pc % 6

    # castling
    if ptype == KING && (from - to).abs == 2
      return to > from ? "O-O" : "O-O-O"
    end

    capture = pos.piece_at(to) != NO_PIECE
    ep = ptype == PAWN && ((from ^ to) & 7) != 0 && pos.piece_at(to) == NO_PIECE
    is_capture = capture || ep

    s = IO::Memory.new
    if ptype == PAWN
      s << FILES[from & 7] << 'x' if is_capture
      s << FILES[to & 7] << RANKS[to >> 3]
      if promo != 0
        s << '=' << "PNBRQK"[promo]
      end
    else
      s << "PNBRQK"[ptype]
      # disambiguation among identical pieces that can legally reach `to`
      buf = Pointer(UInt16).malloc(MAX_MOVES)
      n = pos.generate(buf)
      same_file = false
      same_rank = false
      ambiguous = false
      i = 0
      while i < n
        om = buf[i]
        next_i = i + 1
        if om != m && mv_to(om) == to && pos.piece_at(mv_from(om)) == pc && mv_promo_type(om) == 0
          ambiguous = true
          same_file = true if (mv_from(om) & 7) == (from & 7)
          same_rank = true if (mv_from(om) >> 3) == (from >> 3)
        end
        i = next_i
      end
      if ambiguous
        if !same_file
          s << FILES[from & 7]
        elsif !same_rank
          s << RANKS[from >> 3]
        else
          s << FILES[from & 7] << RANKS[from >> 3]
        end
      end
      s << 'x' if is_capture
      s << FILES[to & 7] << RANKS[to >> 3]
    end

    # check / mate suffix
    child = pos
    child.make_move(m)
    if child.in_check?(child.stm.to_i ^ 1)
      s << (child.generate(Pointer(UInt16).malloc(MAX_MOVES)) == 0 ? '#' : '+')
    end

    s.to_s
    end
  end
end
