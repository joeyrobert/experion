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

    def passed_pawns(pawns : UInt64, enemies : UInt64, color : Int32) : UInt64
      files = enemies | east_one(enemies) | west_one(enemies)
      blocked = color == WHITE ? south_fill(files >> 8) : north_fill(files << 8)
      pawns & ~blocked
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
      occ = pos.occ_all

      # --- pawn structure -----------------------------------------------------
      # passed pawns: no enemy pawns on same or adjacent files ahead
      passed_w = passed_pawns(wp, bp, WHITE)
      passed_b = passed_pawns(bp, wp, BLACK)

      wksq = pos.king_sq(WHITE)
      bksq = pos.king_sq(BLACK)

      pw = passed_w
      while pw != 0
        sq = pw.trailing_zeros_count.to_i!
        rr = sq >> 3
        d_mg += PASSED_MG[rr]
        d_eg += PASSED_EG[rr]
        # blocked: a piece sitting on the stop square blunts the passer
        if rr < 7 && ((1u64 << (sq + 8)) & occ) != 0
          d_mg -= PASSED_MG[rr] // 3
          d_eg -= PASSED_EG[rr] // 4
        end
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
        if rr < 7 && ((1u64 << (sq - 8)) & occ) != 0
          d_mg += PASSED_MG[rr] // 3
          d_eg += PASSED_EG[rr] // 4
        end
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

      # connected passers: each member of an adjacent-file pair
      conn_w = (east_one(passed_w) | west_one(passed_w)) & passed_w
      d_mg += 10 * conn_w.popcount
      d_eg += 22 * conn_w.popcount
      conn_b = (east_one(passed_b) | west_one(passed_b)) & passed_b
      d_mg -= 10 * conn_b.popcount
      d_eg -= 22 * conn_b.popcount

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

      # pawn islands: extra groups of files cost in the endgame
      files_w = south_fill(wp) & 0xFFu64
      files_b = south_fill(bp) & 0xFFu64
      if files_w != 0
        islands = (files_w & ~(files_w << 1)).popcount
        d_mg -= 5 * (islands - 1)
        d_eg -= 12 * (islands - 1)
      end
      if files_b != 0
        islands = (files_b & ~(files_b << 1)).popcount
        d_mg += 5 * (islands - 1)
        d_eg += 12 * (islands - 1)
      end

      # backward pawns: stop square hit by an enemy pawn, no neighbor behind
      b_pawn_atk = ((bp & ~FILE_A_BB) >> 9) | ((bp & ~FILE_H_BB) >> 7)
      bw = ((wp << 8) & b_pawn_atk) >> 8
      while bw != 0
        sq = bw.trailing_zeros_count.to_i!
        span = south_fill(1u64 << sq)
        if ((east_one(span) | west_one(span)) & wp) == 0
          d_mg -= 8
          d_eg -= 12
        end
        bw &= bw - 1
      end
      w_pawn_atk = ((wp & ~FILE_A_BB) << 7) | ((wp & ~FILE_H_BB) << 9)
      bw = ((bp >> 8) & w_pawn_atk) << 8
      while bw != 0
        sq = bw.trailing_zeros_count.to_i!
        span = north_fill(1u64 << sq)
        if ((east_one(span) | west_one(span)) & bp) == 0
          d_mg += 8
          d_eg += 12
        end
        bw &= bw - 1
      end

      # --- rook placement -------------------------------------------------------
      all_pawn_files = south_fill(wp | bp)
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
          elsif (south_fill({% if color == 0 %} wp {% else %} bp {% end %}) & fbit).zero?
            d_mg += sign * 11
            d_eg += sign * 4
          end
          rk &= rk - 1
        end
      {% end %}

      # rook on the 7th, with the enemy king trapped on the 8th or pawns to eat
      wr7 = pos.pieces_of(WHITE, ROOK) & Tables::RANK_BB[6]
      if wr7 != 0 &&
         ((pos.pieces_of(BLACK, KING) & RANK_8_BB) != 0 || (bp & Tables::RANK_BB[6]) != 0)
        n = wr7.popcount
        d_mg += 18 * n
        d_eg += 32 * n
        if n >= 2
          d_mg += 12
          d_eg += 20
        end
      end
      br2 = pos.pieces_of(BLACK, ROOK) & Tables::RANK_BB[1]
      if br2 != 0 &&
         ((pos.pieces_of(WHITE, KING) & RANK_1_BB) != 0 || (wp & Tables::RANK_BB[1]) != 0)
        n = br2.popcount
        d_mg -= 18 * n
        d_eg -= 32 * n
        if n >= 2
          d_mg -= 12
          d_eg -= 20
        end
      end

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

      # pawn storm: our pawns advancing on the files of the enemy king
      bkf = bksq & 7
      storm = wp
      while storm != 0
        sq = storm.trailing_zeros_count.to_i!
        df = ((sq & 7) - bkf).abs
        rr = sq >> 3
        if df <= 1 && rr >= 4 && rr <= 6
          s = (df == 0 ? 10 : 6) + (rr - 4) * 8
          d_mg += s
        end
        storm &= storm - 1
      end
      wkf = wksq & 7
      storm = bp
      while storm != 0
        sq = storm.trailing_zeros_count.to_i!
        df = ((sq & 7) - wkf).abs
        rr = sq >> 3
        if df <= 1 && rr >= 1 && rr <= 3
          s = (df == 0 ? 10 : 6) + (3 - rr) * 8
          d_mg -= s
        end
        storm &= storm - 1
      end

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

      # king tropism: knights and queens closer to the enemy king
      {% for color in [0, 1] %}
        sign_t = {{color == 0 ? 1 : -1}}
        ek = pos.king_sq({{color}} ^ 1)
        kn_t = pos.pieces_of({{color}}, KNIGHT)
        while kn_t != 0
          s = kn_t.trailing_zeros_count.to_i!
          df = ((s & 7) - (ek & 7)).abs
          dr = ((s >> 3) - (ek >> 3)).abs
          d = df > dr ? df : dr
          d_mg += sign_t * (4 - d) * 4 if d <= 4
          kn_t &= kn_t - 1
        end
        q_t = pos.pieces_of({{color}}, QUEEN)
        while q_t != 0
          s = q_t.trailing_zeros_count.to_i!
          df = ((s & 7) - (ek & 7)).abs
          dr = ((s >> 3) - (ek >> 3)).abs
          d = df > dr ? df : dr
          d_mg += sign_t * (5 - d) * 3 if d <= 5
          q_t &= q_t - 1
        end
      {% end %}

      # space: advanced centre pawns
      centre = 0x3c3c3c3c3c3c3c3cu64
      d_mg += 5 * (wp & centre & (Tables::RANK_BB[3] | Tables::RANK_BB[4] | Tables::RANK_BB[5])).popcount
      d_mg -= 5 * (bp & centre & (Tables::RANK_BB[2] | Tables::RANK_BB[3] | Tables::RANK_BB[4])).popcount

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

      # --- hung pieces -----------------------------------------------------
      # A piece attacked by anything and not defended at all. Penalizing
      # "pawn-attacked even if a heavier piece defends" (v//6) scored 40%
      # vs Sungorus over 20 games, worse than hang-veto alone.
      {% for color in [0, 1] %}
        sign_h = {{color == 0 ? 1 : -1}}
        {% for pt in [KNIGHT, BISHOP, ROOK, QUEEN] %}
          pcs_h = pos.pieces_of({{color}}, {{pt}})
          while pcs_h != 0
            sq_h = pcs_h.trailing_zeros_count.to_i!
            if undefended_hang?(pos, sq_h, {{color}})
              v = {{pt == KNIGHT ? 320 : pt == BISHOP ? 330 : pt == ROOK ? 500 : 950}}
              d_mg -= sign_h * (v // 10)
              d_eg -= sign_h * (v // 10)
            end
            pcs_h &= pcs_h - 1
          end
        {% end %}
      {% end %}

      mg += d_mg
      eg += d_eg

      score = (mg * ph + eg * (24 - ph)) // 24
      # Initiative belongs to the side to move, in either color.
      (pos.stm == WHITE.to_u8! ? score : -score) + TEMPO
    end

    # True when `sq` has an enemy attacker other than the king and no
    # defender (king included). King-as-attacker was tried and reverted.
    @[AlwaysInline]
    def undefended_hang?(pos : Position, sq : Int32, color : Int32) : Bool
      occ = pos.occ_all
      them = color ^ 1
      atk = pos.attackers_to(sq, occ, them) & ~pos.pieces_of(them, KING)
      atk != 0 && pos.attackers_to(sq, occ, color) == 0
    end

    # Hung-piece penalty only. Pure NNUE (blend 100) skips classical eval,
    # so search otherwise has no explicit "this piece is en prise" term.
    # Quiet-trained nets under-penalize those positions because game data
    # rarely contains them. STM-relative, no tempo (NNUE already adds it).
    # Tropism + king-zone pressure on top scored 35% vs Crafty and was
    # reverted; hang-only scored 42.5% with the first Black wins.
    def hang_overlay(pos : Position) : Int32
      d = 0
      {% for color in [0, 1] %}
        sign_h = {{color == 0 ? 1 : -1}}
        {% for pt in [KNIGHT, BISHOP, ROOK, QUEEN] %}
          pcs_h = pos.pieces_of({{color}}, {{pt}})
          while pcs_h != 0
            sq_h = pcs_h.trailing_zeros_count.to_i!
            if undefended_hang?(pos, sq_h, {{color}})
              v = {{pt == KNIGHT ? 320 : pt == BISHOP ? 330 : pt == ROOK ? 500 : 950}}
              d -= sign_h * (v // 10)
            end
            pcs_h &= pcs_h - 1
          end
        {% end %}
      {% end %}
      pos.stm == WHITE.to_u8! ? d : -d
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
