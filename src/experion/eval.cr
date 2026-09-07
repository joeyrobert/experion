# Static evaluation v2.
#
# Base layer: material+PSQT accumulated incrementally in Position (mgv/egv).
# Dynamic layer (this file, computed per call): pawn structure, rook placement,
# king shelter and mobility, blended into the same mg/eg tapered score.

module Experion
  module Eval
    extend self

    TEMPO = 12

    MATE        = 30000
    MATE_IN_MAX = 29000

    PASSED_MG = StaticArray[0, 4, 8, 18, 32, 56, 95, 0]
    PASSED_EG = StaticArray[0, 12, 20, 38, 68, 118, 190, 0]

    # --- bitboard fill helpers -------------------------------------------------

    @[AlwaysInline]
    def north_fill(b : UInt64) : UInt64
      b |= b << 8
      b |= b << 16
      b |= b << 32
      b
    end

    @[AlwaysInline]
    def south_fill(b : UInt64) : UInt64
      b |= b >> 8
      b |= b >> 16
      b |= b >> 32
      b
    end

    @[AlwaysInline]
    def east_one(b : UInt64) : UInt64
      (b & ~FILE_H_BB) << 1
    end

    @[AlwaysInline]
    def west_one(b : UInt64) : UInt64
      (b & ~FILE_A_BB) >> 1
    end

    @[AlwaysInline]
    def evaluate(pos : Position) : Int32
      ph = pos.phase
      ph = 24 if ph > 24

      mg = pos.mgv
      eg = pos.egv
      d_mg = 0
      d_eg = 0

      wp = pos.pieces_of(WHITE, PAWN)
      bp = pos.pieces_of(BLACK, PAWN)

      # --- pawn structure -----------------------------------------------------
      # passed pawns: no enemy pawns on same or adjacent files ahead
      bp_front = north_fill(bp | east_one(bp) | west_one(bp))
      passed_w = wp & ~bp_front
      wp_front = south_fill(wp | east_one(wp) | west_one(wp))
      passed_b = bp & ~wp_front

      wksq = pos.king_sq(WHITE)
      bksq = pos.king_sq(BLACK)

      pw = passed_w
      while pw != 0
        sq = pw.trailing_zeros_count.to_i!
        rr = sq >> 3
        d_mg += PASSED_MG[rr]
        d_eg += PASSED_EG[rr]
        # endgame: passers shine when OUR king escorts and THEIR king is far
        df = (sq & 7) - (bksq & 7)
        dr = (sq >> 3) - (bksq >> 3)
        d_eg += ((df.abs > dr.abs ? df.abs : dr.abs) * 5)
        df = (sq & 7) - (wksq & 7)
        dr = (sq >> 3) - (wksq >> 3)
        d_eg -= ((df.abs > dr.abs ? df.abs : dr.abs) * 2)
        # friendly rook behind the passer on its file
        if ((pos.pieces_of(WHITE, ROOK) & south_fill(1u64 << sq)) != 0) &&
           ((FILE_A_BB << (sq & 7) & pos.pieces_of(WHITE, ROOK)) != 0)
          d_mg += 22
          d_eg += 14
        end
        # protected by a friendly pawn
        if (Tables.pawn_attacks(BLACK, sq) & wp) != 0
          d_mg += 16
          d_eg += 12
        end
        pw &= pw - 1
      end

      pb = passed_b
      while pb != 0
        sq = pb.trailing_zeros_count.to_i!
        rr = 7 - (sq >> 3)
        d_mg -= PASSED_MG[rr]
        d_eg -= PASSED_EG[rr]
        df = (sq & 7) - (wksq & 7)
        dr = (sq >> 3) - (wksq >> 3)
        d_eg -= ((df.abs > dr.abs ? df.abs : dr.abs) * 5)
        df = (sq & 7) - (bksq & 7)
        dr = (sq >> 3) - (bksq >> 3)
        d_eg += ((df.abs > dr.abs ? df.abs : dr.abs) * 2)
        # enemy rook behind the passer on its file
        if ((pos.pieces_of(BLACK, ROOK) & north_fill(1u64 << sq)) != 0) &&
           ((FILE_A_BB << (sq & 7) & pos.pieces_of(BLACK, ROOK)) != 0)
          d_mg -= 22
          d_eg -= 14
        end
        # protected by a friendly pawn
        if (Tables.pawn_attacks(WHITE, sq) & bp) != 0
          d_mg -= 16
          d_eg -= 12
        end
        pb &= pb - 1
      end

      # doubled pawns
      dbl_w = wp & north_fill(wp << 8)
      dbl_b = bp & south_fill(bp >> 8)
      d_mg -= 10 * dbl_w.popcount
      d_eg -= 18 * dbl_w.popcount
      d_mg += 10 * dbl_b.popcount
      d_eg += 18 * dbl_b.popcount

      # isolated pawns (no friendly pawn on adjacent files)
      w_adj = east_one(wp) | west_one(wp)
      iso_w = wp & ~south_fill(w_adj) & ~north_fill(w_adj)
      b_adj = east_one(bp) | west_one(bp)
      iso_b = bp & ~south_fill(b_adj) & ~north_fill(b_adj)
      d_mg -= 14 * iso_w.popcount
      d_eg -= 16 * iso_w.popcount
      d_mg += 14 * iso_b.popcount
      d_eg += 16 * iso_b.popcount

      occ = pos.occ_all

      # --- rook placement -------------------------------------------------------
      all_pawn_files = north_fill(wp | bp)
      {% for color in [0, 1] %}
        sign = {{color == 0 ? 1 : -1}}
        rooks = pos.pieces_of({{color}}, ROOK)
        rk = rooks
        while rk != 0
          sq = rk.trailing_zeros_count.to_i!
          fbit = 1u64 << (sq & 7)
          if (all_pawn_files & fbit).zero?
            d_mg += sign * 24
            d_eg += sign * 8
          elsif ({% if color == 0 %} wp {% else %} bp {% end %} & fbit).zero?
            d_mg += sign * 11
            d_eg += sign * 4
          end
          rk &= rk - 1
        end
      {% end %}

      # --- king shelter (middlegame) ---------------------------------------------
      {% for color in [0, 1] %}
        sign2 = {{color == 0 ? 1 : -1}}
        ksq = pos.king_sq({{color}})
        kf = ksq & 7
        kr = ksq >> 3
        {% if color == 0 %}
          fr = kr + 1
          in_board = fr < 8
          my_pawns_sh = wp
        {% else %}
          fr = kr - 1
          in_board = fr >= 0
          my_pawns_sh = bp
        {% end %}
        if in_board
          shield = 0u64
          center_bit = 1u64 << (fr * 8 + kf)
          shield |= center_bit
          shield |= (1u64 << (fr * 8 + kf - 1)) if kf > 0
          shield |= (1u64 << (fr * 8 + kf + 1)) if kf < 7
          cnt = (shield & my_pawns_sh).popcount
          d_mg += sign2 * (cnt - 2) * 12
        end
      {% end %}

      {% unless flag?(:slow_eval) %}
      # --- mobility -----------------------------------------------------------------
      us_occ0 = pos.occ_of(WHITE)
      them_occ0 = pos.occ_of(BLACK)

      kn = pos.pieces_of(WHITE, KNIGHT)
      while kn != 0
        s = kn.trailing_zeros_count.to_i!
        d_mg += 4 * (Tables.knight_attacks(s) & ~us_occ0).popcount
        kn &= kn - 1
      end
      kn = pos.pieces_of(BLACK, KNIGHT)
      while kn != 0
        s = kn.trailing_zeros_count.to_i!
        d_mg -= 4 * (Tables.knight_attacks(s) & ~them_occ0).popcount
        kn &= kn - 1
      end

      bi = pos.pieces_of(WHITE, BISHOP)
      while bi != 0
        s = bi.trailing_zeros_count.to_i!
        c = (Tables.bishop_attacks(s, occ) & ~us_occ0).popcount
        d_mg += 4 * c
        d_eg += 3 * c
        bi &= bi - 1
      end
      bi = pos.pieces_of(BLACK, BISHOP)
      while bi != 0
        s = bi.trailing_zeros_count.to_i!
        c = (Tables.bishop_attacks(s, occ) & ~them_occ0).popcount
        d_mg -= 4 * c
        d_eg -= 3 * c
        bi &= bi - 1
      end

      rk = pos.pieces_of(WHITE, ROOK)
      while rk != 0
        s = rk.trailing_zeros_count.to_i!
        c = (Tables.rook_attacks(s, occ) & ~us_occ0).popcount
        d_mg += 2 * c
        d_eg += 2 * c
        rk &= rk - 1
      end
      rk = pos.pieces_of(BLACK, ROOK)
      while rk != 0
        s = rk.trailing_zeros_count.to_i!
        c = (Tables.rook_attacks(s, occ) & ~them_occ0).popcount
        d_mg -= 2 * c
        d_eg -= 2 * c
        rk &= rk - 1
      end

      qu = pos.pieces_of(WHITE, QUEEN)
      while qu != 0
        s = qu.trailing_zeros_count.to_i!
        c = (Tables.queen_attacks(s, occ) & ~us_occ0).popcount
        d_mg += c
        d_eg += c
        qu &= qu - 1
      end
      qu = pos.pieces_of(BLACK, QUEEN)
      while qu != 0
        s = qu.trailing_zeros_count.to_i!
        c = (Tables.queen_attacks(s, occ) & ~them_occ0).popcount
        d_mg -= c
        d_eg -= c
        qu &= qu - 1
      end

      # --- king attack pressure (middlegame) ---------------------------------
      # `color`'s own pieces attacking the zone around the ENEMY king (not
      # its own king — that would reward a side for merely having pieces
      # near its own king, the opposite of an attack-pressure bonus, and
      # never penalize a real mating attack against it).
      {% for color in [0, 1] %}
        ksq_att = pos.king_sq({{color}} ^ 1)
        zone = Tables.king_attacks(ksq_att) | (1u64 << ksq_att)
        pres = 0
        kn_a = pos.pieces_of({{color}}, KNIGHT)
        while kn_a != 0
          s2 = kn_a.trailing_zeros_count.to_i!
          pres += 20 if (Tables.knight_attacks(s2) & zone) != 0
          kn_a &= kn_a - 1
        end
        bi_a = pos.pieces_of({{color}}, BISHOP)
        while bi_a != 0
          s2 = bi_a.trailing_zeros_count.to_i!
          pres += 22 if (Tables.bishop_attacks(s2, occ) & zone) != 0
          bi_a &= bi_a - 1
        end
        rk_a = pos.pieces_of({{color}}, ROOK)
        while rk_a != 0
          s2 = rk_a.trailing_zeros_count.to_i!
          pres += 28 if (Tables.rook_attacks(s2, occ) & zone) != 0
          rk_a &= rk_a - 1
        end
        qu_a = pos.pieces_of({{color}}, QUEEN)
        while qu_a != 0
          s2 = qu_a.trailing_zeros_count.to_i!
          pres += 36 if (Tables.queen_attacks(s2, occ) & zone) != 0
          qu_a &= qu_a - 1
        end
        {% if color == 0 %}
          d_mg += pres
          # bonus for multiple attackers on king zone (scaling attack)
          d_mg += pres * pres // 800 if pres > 60
        {% else %}
          d_mg -= pres
          d_mg -= pres * pres // 800 if pres > 60
        {% end %}
      {% end %}

      # --- outposts ------------------------------------------------------------------
      {% for color in [0, 1] %}
        sign_o = {{color == 0 ? 1 : -1}}
        {% if color == 0 %}
          my_p = wp
          their_p = bp
        {% else %}
          my_p = bp
          their_p = wp
        {% end %}
        {% if color == 0 %}
          their_p_attacks = south_fill(east_one(bp) | west_one(bp))
        {% else %}
          their_p_attacks = north_fill(east_one(wp) | west_one(wp))
        {% end %}
        {% for pt in [KNIGHT, BISHOP] %}
          pcs_o = pos.pieces_of({{color}}, {{pt}})
          while pcs_o != 0
            s3 = pcs_o.trailing_zeros_count.to_i!
            r3 = s3 >> 3
            {% if color == 0 %}
              in_zone = r3 >= 3 && r3 <= 5
            {% else %}
              in_zone = r3 >= 2 && r3 <= 4
            {% end %}
            if in_zone
              sq_bit = 1u64 << s3
              defended = (Tables.pawn_attacks({{color}} ^ 1, s3) & my_p) != 0
              not_attackable = (sq_bit & their_p_attacks).zero?
              if defended && not_attackable
                d_mg += sign_o * ({{pt == KNIGHT ? 22 : 14}})
              end
            end
            pcs_o &= pcs_o - 1
          end
        {% end %}
      {% end %}

      {% end %} # end FAST_EVAL block

      # bishop pair
      d_mg += 26 if pos.pieces_of(WHITE, BISHOP).popcount >= 2
      d_eg += 40 if pos.pieces_of(WHITE, BISHOP).popcount >= 2
      d_mg -= 26 if pos.pieces_of(BLACK, BISHOP).popcount >= 2
      d_eg -= 40 if pos.pieces_of(BLACK, BISHOP).popcount >= 2

      mg += d_mg
      eg += d_eg

      # --- hung pieces -----------------------------------------------------
      # for each non-pawn piece, see if any enemy piece attacks it. If
      # so, check if a friendly piece can recapture. If not, it's a
      # tactical problem. The penalty is the piece value times a
      # small fraction (most positions have a defender).
      {% for color in [0, 1] %}
        sign_h = {{color == 0 ? 1 : -1}}
        {% for pt in [KNIGHT, BISHOP, ROOK, QUEEN] %}
          pcs_h = pos.pieces_of({{color}}, {{pt}})
          while pcs_h != 0
            sq_h = pcs_h.trailing_zeros_count.to_i!
            # any enemy piece attacks this square?
            attacked = (Tables.pawn_attacks({{color}}, sq_h) & pos.pieces_of({{color}} ^ 1, PAWN)) |
                       (Tables.knight_attacks(sq_h) & pos.pieces_of({{color}} ^ 1, KNIGHT)) |
                       (Tables.bishop_attacks(sq_h, occ) & pos.pieces_of({{color}} ^ 1, BISHOP)) |
                       (Tables.rook_attacks(sq_h, occ) & pos.pieces_of({{color}} ^ 1, ROOK)) |
                       (Tables.queen_attacks(sq_h, occ) & pos.pieces_of({{color}} ^ 1, QUEEN))
            if attacked != 0
              # any friendly piece defends this square?
              defended = (Tables.pawn_attacks({{color}} ^ 1, sq_h) & pos.pieces_of({{color}}, PAWN)) |
                         (Tables.knight_attacks(sq_h) & pos.pieces_of({{color}}, KNIGHT)) |
                         (Tables.bishop_attacks(sq_h, occ) & pos.pieces_of({{color}}, BISHOP)) |
                         (Tables.rook_attacks(sq_h, occ) & pos.pieces_of({{color}}, ROOK)) |
                         (Tables.queen_attacks(sq_h, occ) & pos.pieces_of({{color}}, QUEEN)) |
                         (Tables.king_attacks(sq_h) & pos.pieces_of({{color}}, KING))
              if defended == 0
                # hanging: penalize by piece value (small fraction)
                v = {{pt == KNIGHT ? 320 : pt == BISHOP ? 330 : pt == ROOK ? 500 : 950}}
                d_mg -= sign_h * (v // 10)
                d_eg -= sign_h * (v // 10)
              end
            end
            pcs_h &= pcs_h - 1
          end
        {% end %}
      {% end %}

      mg += d_mg
      eg += d_eg

      score = (mg * ph + eg * (24 - ph)) // 24
      # tempo always belongs to the side that has the initiative (white in
      # normal chess, since they move first). Add to white's POV value
      # first, then flip at the end so the caller gets side-to-move POV.
      score += TEMPO

      pos.stm == WHITE.to_u8! ? score : -score
    end

    # No way to force mate: bare kings, or king + single minor vs bare king.
    def insufficient_material?(pos : Position) : Bool
      return true if (pos.occ_all & ~(pos.pieces_of(0, KING) | pos.pieces_of(1, KING))).zero?
      white_rest = pos.occ_of(WHITE) & ~pos.pieces_of(WHITE, KING)
      black_rest = pos.occ_of(BLACK) & ~pos.pieces_of(BLACK, KING)
      if black_rest.zero?
        return true if white_rest.popcount == 1 &&
                       ((white_rest & pos.pieces_of(WHITE, KNIGHT)) != 0 ||
                        (white_rest & pos.pieces_of(WHITE, BISHOP)) != 0)
      end
      if white_rest.zero?
        return true if black_rest.popcount == 1 &&
                       ((black_rest & pos.pieces_of(BLACK, KNIGHT)) != 0 ||
                        (black_rest & pos.pieces_of(BLACK, BISHOP)) != 0)
      end
      false
    end
  end
end
