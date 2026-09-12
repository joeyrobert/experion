# Position: immutable-by-convention value struct with copy-make semantics.
#
# `child = parent` copies the whole struct (bitboards are inline StaticArrays),
# then `child.make_move(m)` mutates the copy in place. The parent is never
# touched, which gives us undo-free search and trivially correct state
# restoration.
#
# Score convention: mgv/egv accumulate (white - black) in centipawns.

module Experion
  module Zobrist
    extend self

    PIECE = Pointer(UInt64).malloc(12 * 64)
    CASTLE = Pointer(UInt64).malloc(16)
    EP_FILE = Pointer(UInt64).malloc(8)

    @@side = 0u64
    @@initialized = false

    def self.side : UInt64
      @@side
    end

    def init : Nil
      return if @@initialized
      @@initialized = true

      rng = Zrng.new(0x853C49E6748FEA9Bu64)
      i = 0
      while i < 12 * 64
        PIECE[i] = rng.next
        i += 1
      end
      i = 0
      while i < 16
        CASTLE[i] = rng.next
        i += 1
      end
      i = 0
      while i < 8
        EP_FILE[i] = rng.next
        i += 1
      end
      @@side = rng.next
    end

    private struct Zrng
      def initialize(seed : UInt64)
        @state = seed
      end

      def next : UInt64
        x = @state &+ 0x9E3779B97F4A7C15u64
        @state = x
        z = x
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9u64
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EBu64
        z ^ (z >> 31)
      end
    end
  end

  # castling-rights removal masks per square: rights &= MASK[from] & MASK[to]
  CASTLE_MASK = StaticArray(UInt8, 64).new(15u8)
  CASTLE_MASK[A1] = 15u8 & ~CASTLE_WQ
  CASTLE_MASK[E1] = 15u8 & ~(CASTLE_WK | CASTLE_WQ)
  CASTLE_MASK[H1] = 15u8 & ~CASTLE_WK
  CASTLE_MASK[A8] = 15u8 & ~CASTLE_BQ
  CASTLE_MASK[E8] = 15u8 & ~(CASTLE_BK | CASTLE_BQ)
  CASTLE_MASK[H8] = 15u8 & ~CASTLE_BK

  struct Position
    include Moves

    @bb = StaticArray(UInt64, 12).new(0u64)
    @occ = StaticArray(UInt64, 3).new(0u64)
    @board = StaticArray(UInt8, 64).new(NO_PIECE)
    @stm : UInt8 = WHITE.to_u8!
    @castling : UInt8 = 0u8
    @ep : UInt8 = NO_SQUARE
    @halfmove : UInt8 = 0u8
    @fullmove : Int16 = 1i16
    @hash : UInt64 = 0u64
    @mgv : Int32 = 0
    @egv : Int32 = 0
    @phase : Int32 = 0

    def initialize(fen : String)
      parts = fen.split
      raise "bad FEN: #{fen}" if parts.size < 1

      sq = 56
      parts[0].each_char do |c|
        case c
        when '/'
          sq -= 16
        when .ascii_number?
          sq += c - '0'
        else
          pc = PIECE_CHAR.index(c)
          raise "bad FEN piece #{c} in #{fen}" if pc.nil?
          @board[sq] = pc.to_u8!
          sq += 1
        end
      end
      raise "bad FEN board: #{fen}" unless sq == 8

      # rebuild bitboards + incremental state from the mailbox
      sq = 0
      while sq < 64
        pc = @board.unsafe_fetch(sq)
        unless pc == NO_PIECE
          bit = 1u64 << sq
          @bb.unsafe_put(pc, @bb.unsafe_fetch(pc) | bit)
          color = pc >= 6 ? BLACK : WHITE
          @occ.unsafe_put(color, @occ.unsafe_fetch(color) | bit)
          @occ.unsafe_put(2, @occ.unsafe_fetch(2) | bit)
          @mgv += Psqt.mg(pc, sq)
          @egv += Psqt.eg(pc, sq)
          @phase += Psqt.phase_of(pc)
        end
        sq += 1
      end

      @stm = parts.size > 1 && parts[1] == "b" ? BLACK.to_u8! : WHITE.to_u8!

      if parts.size > 2 && parts[2] != "-"
        parts[2].each_char do |c|
          case c
          when 'K' then @castling |= CASTLE_WK
          when 'Q' then @castling |= CASTLE_WQ
          when 'k' then @castling |= CASTLE_BK
          when 'q' then @castling |= CASTLE_BQ
          end
        end
      end

      if parts.size > 3 && parts[3] != "-"
        f = FILES.index(parts[3][0])
        r = RANKS.index(parts[3][1])
        if f && r
          @ep = (r * 8 + f).to_u8!
        end
      end

      @halfmove = parts.size > 4 ? (parts[4].to_i? || 0).clamp(0, 255).to_u8! : 0u8
      @fullmove = parts.size > 5 ? (parts[5].to_i? || 1).clamp(1, 32767).to_i16! : 1i16

      # normalize: an ep square only counts (and hashes) if a capture is possible
      if @ep != NO_SQUARE
        them = @stm ^ 1
        capturers = Tables.pawn_attacks(@stm, @ep) & @bb.unsafe_fetch(PAWN + 6 * them)
        @ep = NO_SQUARE if capturers.zero?
      end

      @hash = compute_hash
    end

    def self.startpos : Position
      Position.new(STARTPOS_FEN)
    end

    private def compute_hash : UInt64
      h = 0u64
      sq = 0
      while sq < 64
        pc = @board.unsafe_fetch(sq)
        h ^= Zobrist::PIECE[(pc.to_i << 6) + sq] unless pc == NO_PIECE
        sq += 1
      end
      h ^= Zobrist::CASTLE[@castling]
      h ^= Zobrist::EP_FILE[@ep & 7] unless @ep == NO_SQUARE
      h ^= Zobrist.side unless @stm == WHITE
      h
    end

    # --- accessors ------------------------------------------------------------

    @[AlwaysInline]
    def pieces(pc : Int) : UInt64
      @bb.unsafe_fetch(pc)
    end

    @[AlwaysInline]
    def pieces_of(color : Int, ptype : Int) : UInt64
      @bb.unsafe_fetch(color * 6 + ptype)
    end

    @[AlwaysInline]
    def occ_of(color : Int) : UInt64
      @occ.unsafe_fetch(color)
    end

    @[AlwaysInline]
    def occ_all : UInt64
      @occ.unsafe_fetch(2)
    end

    @[AlwaysInline]
    def piece_at(sq : Int) : UInt8
      @board.unsafe_fetch(sq)
    end

    @[AlwaysInline]
    def stm : UInt8
      @stm
    end

    @[AlwaysInline]
    def castling : UInt8
      @castling
    end

    @[AlwaysInline]
    def ep : UInt8
      @ep
    end

    @[AlwaysInline]
    def halfmove : UInt8
      @halfmove
    end

    @[AlwaysInline]
    def fullmove : Int16
      @fullmove
    end

    @[AlwaysInline]
    def hash : UInt64
      @hash
    end

    @[AlwaysInline]
    def mgv : Int32
      @mgv
    end

    @[AlwaysInline]
    def egv : Int32
      @egv
    end

    @[AlwaysInline]
    def phase : Int32
      @phase
    end

    @[AlwaysInline]
    def king_sq(color : Int) : Int32
      @bb.unsafe_fetch(color * 6 + KING).trailing_zeros_count.to_i!
    end

    # --- attack queries ---------------------------------------------------------

    # Is `sq` attacked by any piece of color `by` given occupancy `occ`?
    @[AlwaysInline]
    def attacked_by?(sq : Int, by : Int, occ : UInt64) : Bool
      return true if (Tables.pawn_attacks(by ^ 1, sq) & @bb.unsafe_fetch(PAWN + 6 * by)) != 0
      return true if (Tables.knight_attacks(sq) & @bb.unsafe_fetch(KNIGHT + 6 * by)) != 0
      return true if (Tables.king_attacks(sq) & @bb.unsafe_fetch(KING + 6 * by)) != 0
      return true if (Tables.bishop_attacks(sq, occ) & (@bb.unsafe_fetch(BISHOP + 6 * by) | @bb.unsafe_fetch(QUEEN + 6 * by))) != 0
      (Tables.rook_attacks(sq, occ) & (@bb.unsafe_fetch(ROOK + 6 * by) | @bb.unsafe_fetch(QUEEN + 6 * by))) != 0
    end

    # Bitboard of all pieces of color `by` attacking `sq` given occupancy `occ`.
    def attackers_to(sq : Int, occ : UInt64, by : Int) : UInt64
      b = (Tables.pawn_attacks(by ^ 1, sq) & @bb.unsafe_fetch(PAWN + 6 * by)) |
          (Tables.knight_attacks(sq) & @bb.unsafe_fetch(KNIGHT + 6 * by)) |
          (Tables.king_attacks(sq) & @bb.unsafe_fetch(KING + 6 * by)) |
          (Tables.bishop_attacks(sq, occ) & (@bb.unsafe_fetch(BISHOP + 6 * by) | @bb.unsafe_fetch(QUEEN + 6 * by))) |
          (Tables.rook_attacks(sq, occ) & (@bb.unsafe_fetch(ROOK + 6 * by) | @bb.unsafe_fetch(QUEEN + 6 * by)))
      b
    end

    @[AlwaysInline]
    def in_check?(color : Int = @stm) : Bool
      attacked_by?(king_sq(color), color ^ 1, occ_all)
    end

    # --- make move (in place on a copy) ------------------------------------------

    # Mutates self. Callers must copy first: `child = parent; child.make_move(m)`.
    def make_move(m : UInt16, upd_hash : Bool = true) : Nil
      from = mv_from(m)
      to = mv_to(m)

      us = @stm
      them = (us ^ 1).to_u8!
      pc = @board.unsafe_fetch(from)

      # structural special-move detection (see move.cr)
      is_castle = (pc % 6) == KING && (from - to).abs == 2
      promo = mv_promo_type(m)
      is_ep = (pc % 6) == PAWN && ((from ^ to) & 7) != 0 &&
              @board.unsafe_fetch(to) == NO_PIECE

      cap_sq = is_ep ? (us == WHITE.to_u8! ? to - 8 : to + 8) : to
      captured = @board.unsafe_fetch(cap_sq)

      bb = @bb.to_unsafe
      boardp = @board.to_unsafe
      occp = @occ.to_unsafe

      bit_from = 1u64 << from
      bit_to = 1u64 << to

      h = @hash
      mg = @mgv
      eg = @egv
      ph = @phase

      # 1. remove captured piece
      if captured != NO_PIECE
        bit_cap = 1u64 << cap_sq
        bb[captured] &= ~bit_cap
        occp[them] &= ~bit_cap
        occp[2] &= ~bit_cap
        boardp[cap_sq] = NO_PIECE
        mg -= Psqt.mg(captured, cap_sq)
        eg -= Psqt.eg(captured, cap_sq)
        ph -= Psqt.phase_of(captured)
        h ^= Zobrist::PIECE[(captured.to_i << 6) + cap_sq] if upd_hash
      end

      # 2. lift the moving piece
      bb[pc] &= ~bit_from
      occp[us] &= ~bit_from
      occp[2] &= ~bit_from
      boardp[from] = NO_PIECE
      h ^= Zobrist::PIECE[(pc.to_i << 6) + from] if upd_hash
      mg -= Psqt.mg(pc, from)
      eg -= Psqt.eg(pc, from)

      # 3. place it (or the promoted piece)
      placed = pc
      if promo != 0
        placed = (us * 6 + promo).to_u8!
        ph += Psqt.phase_of(placed)
      end
      bb[placed] |= bit_to
      occp[us] |= bit_to
      occp[2] |= bit_to
      boardp[to] = placed
      h ^= Zobrist::PIECE[(placed.to_i << 6) + to] if upd_hash
      mg += Psqt.mg(placed, to)
      eg += Psqt.eg(placed, to)

      # 4. castling: move the rook too
      if is_castle
        rfrom = 0
        rto = 0
        case to
        when 6  then rfrom = 7; rto = 5    # white O-O
        when 2  then rfrom = 0; rto = 3    # white O-O-O
        when 62 then rfrom = 63; rto = 61  # black O-O
        else        rfrom = 56; rto = 59   # black O-O-O (to == 58)
        end
        rook = boardp[rfrom]
        bit_rf = 1u64 << rfrom
        bit_rt = 1u64 << rto
        bb[rook] &= ~bit_rf
        bb[rook] |= bit_rt
        occp[us] = (occp[us] & ~bit_rf) | bit_rt
        occp[2] = (occp[2] & ~bit_rf) | bit_rt
        boardp[rfrom] = NO_PIECE
        boardp[rto] = rook
        h ^= Zobrist::PIECE[(rook.to_i << 6) + rfrom] ^ Zobrist::PIECE[(rook.to_i << 6) + rto] if upd_hash
        mg += Psqt.mg(rook, rto) - Psqt.mg(rook, rfrom)
        eg += Psqt.eg(rook, rto) - Psqt.eg(rook, rfrom)
      end

      # 5. castling rights
      old_castling = @castling
      new_castling = old_castling & CASTLE_MASK.unsafe_fetch(from) & CASTLE_MASK.unsafe_fetch(to)
      if new_castling != old_castling
        @castling = new_castling
        h ^= Zobrist::CASTLE[old_castling] ^ Zobrist::CASTLE[new_castling] if upd_hash
      end

      # 6. en passant square (normalized: only if capturable)
      old_ep = @ep
      new_ep = NO_SQUARE
      if (pc % 6) == PAWN && (from - to).abs == 16
        ep_cand = ((from + to) >> 1).to_u8!
        unless (Tables.pawn_attacks(us, ep_cand) & bb[PAWN + 6 * them]).zero?
          new_ep = ep_cand
        end
      end
      if old_ep != new_ep
        @ep = new_ep
        if upd_hash
          h ^= Zobrist::EP_FILE[old_ep & 7] unless old_ep == NO_SQUARE
          h ^= Zobrist::EP_FILE[new_ep & 7] unless new_ep == NO_SQUARE
        end
      end

      # 7. clocks
      @halfmove = if (pc % 6) == PAWN || captured != NO_PIECE
                    0u8
                  else
                    (@halfmove < 200 ? @halfmove + 1u8 : 200u8)
                  end
      @fullmove += 1i16 if us == BLACK.to_u8!

      # 8. side to move
      @stm = them
      h ^= Zobrist.side if upd_hash

      @hash = h
      @mgv = mg
      @egv = eg
      @phase = ph
    end

    # Zobrist key of `self` after `m`, without copying the position. Used to
    # probe the child's TT slot for move ordering.
    def hash_after(m : UInt16) : UInt64
      from = mv_from(m)
      to = mv_to(m)
      us = @stm
      them = (us ^ 1).to_u8!
      pc = @board.unsafe_fetch(from)
      is_castle = (pc % 6) == KING && (from - to).abs == 2
      promo = mv_promo_type(m)
      is_ep = (pc % 6) == PAWN && ((from ^ to) & 7) != 0 &&
              @board.unsafe_fetch(to) == NO_PIECE
      cap_sq = is_ep ? (us == WHITE.to_u8! ? to - 8 : to + 8) : to
      captured = @board.unsafe_fetch(cap_sq)

      h = @hash
      if captured != NO_PIECE
        h ^= Zobrist::PIECE[(captured.to_i << 6) + cap_sq]
      end
      h ^= Zobrist::PIECE[(pc.to_i << 6) + from]
      placed = promo != 0 ? (us * 6 + promo).to_u8! : pc
      h ^= Zobrist::PIECE[(placed.to_i << 6) + to]
      if is_castle
        rfrom = 0
        rto = 0
        case to
        when 6  then rfrom = 7; rto = 5
        when 2  then rfrom = 0; rto = 3
        when 62 then rfrom = 63; rto = 61
        else         rfrom = 56; rto = 59
        end
        rook = @board.unsafe_fetch(rfrom)
        h ^= Zobrist::PIECE[(rook.to_i << 6) + rfrom] ^ Zobrist::PIECE[(rook.to_i << 6) + rto]
      end
      old_castling = @castling
      new_castling = old_castling & CASTLE_MASK.unsafe_fetch(from) & CASTLE_MASK.unsafe_fetch(to)
      if new_castling != old_castling
        h ^= Zobrist::CASTLE[old_castling] ^ Zobrist::CASTLE[new_castling]
      end
      old_ep = @ep
      new_ep = NO_SQUARE
      if (pc % 6) == PAWN && (from - to).abs == 16
        ep_cand = ((from + to) >> 1).to_u8!
        unless (Tables.pawn_attacks(us, ep_cand) & @bb.unsafe_fetch(PAWN + 6 * them)).zero?
          new_ep = ep_cand
        end
      end
      if old_ep != new_ep
        h ^= Zobrist::EP_FILE[old_ep & 7] unless old_ep == NO_SQUARE
        h ^= Zobrist::EP_FILE[new_ep & 7] unless new_ep == NO_SQUARE
      end
      h ^ Zobrist.side
    end

    # Null move (for search): pass the turn, clear ep.
    def make_null_move(upd_hash : Bool = true) : Nil
      old_ep = @ep
      @ep = NO_SQUARE
      @stm = (@stm ^ 1).to_u8!
      @halfmove = (@halfmove < 200 ? @halfmove + 1u8 : 200u8)
      @fullmove += 1i16 if @stm == BLACK.to_u8!
      if upd_hash
        h = @hash
        h ^= Zobrist::EP_FILE[old_ep & 7] unless old_ep == NO_SQUARE
        h ^= Zobrist.side
        @hash = h
      end
    end

    # --- output -------------------------------------------------------------------

    def to_fen : String
      String.build do |s|
        rank = 7
        while rank >= 0
          empty = 0
          file = 0
          while file < 8
            pc = @board.unsafe_fetch(rank * 8 + file)
            if pc == NO_PIECE
              empty += 1
            else
              s << empty if empty > 0
              empty = 0
              s << PIECE_CHAR[pc]
            end
            file += 1
          end
          s << empty if empty > 0
          s << '/' if rank > 0
          rank -= 1
        end
        s << ' ' << (@stm == WHITE.to_u8! ? 'w' : 'b') << ' '
        if @castling.zero?
          s << '-'
        else
          s << 'K' if (@castling & CASTLE_WK) != 0
          s << 'Q' if (@castling & CASTLE_WQ) != 0
          s << 'k' if (@castling & CASTLE_BK) != 0
          s << 'q' if (@castling & CASTLE_BQ) != 0
        end
        s << ' '
        if @ep == NO_SQUARE
          s << '-'
        else
          s << FILES[@ep & 7] << RANKS[@ep >> 3]
        end
        s << ' ' << @halfmove << ' ' << @fullmove
      end
    end

    def pretty : String
      String.build do |s|
        rank = 7
        while rank >= 0
          s << (rank + 1).to_s << "  "
          file = 0
          while file < 8
            pc = @board.unsafe_fetch(rank * 8 + file)
            s << (pc == NO_PIECE ? '.' : PIECE_CHAR[pc]) << ' '
            file += 1
          end
          s << '\n'
          rank -= 1
        end
        s << "   a b c d e f g h\n"
        s << "fen: " << to_fen << "\n"
      end
    end
  end
end
