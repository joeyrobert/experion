# Fully legal move generation.
#
# Strategy (Stockfish-style): compute checkers, pinned pieces and a
# "check mask" once, then generate only legal moves directly. Because every
# emitted move is legal, perft can bulk-count at depth 1 without making moves.
#
# The generator is stamped out twice by a macro — `generate` (all moves) and
# `generate_captures` (captures + promotions, for quiescence) — and the pawn
# section is specialized per color at compile time. One source of truth,
# zero runtime flags in the hot path.

module Experion
  FILE_A_BB = 0x0101010101010101u64
  FILE_H_BB = 0x8080808080808080u64
  RANK_1_BB = 0x00000000000000FFu64
  RANK_3_BB = 0x0000000000FF0000u64
  RANK_6_BB = 0x0000FF0000000000u64
  RANK_8_BB = 0xFF00000000000000u64

  struct Position
    def generate(out_ptr : Pointer(UInt16)) : Int32
      gen_legal(out_ptr)
    end

    def generate_captures(out_ptr : Pointer(UInt16)) : Int32
      gen_caps(out_ptr)
    end

    # emits one move + bump count
    macro emit(mv)
      out_ptr[count] = {{mv}}
      count += 1
    end

    # emits all four promotions from -> to
    macro emit_promos(from_sq, to_sq)
      out_ptr[count] = move_promo({{from_sq}}, {{to_sq}}, KNIGHT); count += 1
      out_ptr[count] = move_promo({{from_sq}}, {{to_sq}}, BISHOP); count += 1
      out_ptr[count] = move_promo({{from_sq}}, {{to_sq}}, ROOK);   count += 1
      out_ptr[count] = move_promo({{from_sq}}, {{to_sq}}, QUEEN);  count += 1
    end

    macro define_gen(fname, caps_only)
      private def {{fname.id}}(out_ptr : Pointer(UInt16)) : Int32
        count = 0
        us = @stm.to_i
        them = us ^ 1
        occ = occ_all
        us_occ = occ_of(us)
        them_occ = occ_of(them)

        ksq = king_sq(us)
        king_bit = 1u64 << ksq

        their_bq = pieces_of(them, BISHOP) | pieces_of(them, QUEEN)
        their_rq = pieces_of(them, ROOK) | pieces_of(them, QUEEN)

        checkers = attackers_to(ksq, occ, them)

        # potential pinners: scan rays with EMPTY occupancy so sliders behind
        # blockers are visible; classify each via the between-set population
        snipers = (Tables.bishop_attacks(ksq, 0u64) & their_bq) |
                  (Tables.rook_attacks(ksq, 0u64) & their_rq)
        pinned = 0u64
        sn = snipers
        while sn != 0
          s = sn.trailing_zeros_count
          sn &= sn - 1
          btw = Tables.between(ksq, s) & occ
          if btw != 0 && (btw & (btw - 1)) == 0
            pinned |= btw
          end
        end

        if checkers.zero?
          check_mask = 0xFFFFFFFFFFFFFFFFu64
          dbl_check = false
        elsif (checkers & (checkers - 1)).zero?
          c = checkers.trailing_zeros_count
          check_mask = checkers | Tables.between(ksq, c)
          dbl_check = false
        else
          check_mask = 0u64
          dbl_check = true
        end

        # --- king moves -------------------------------------------------------
        ka = Tables.king_attacks(ksq) & ~us_occ
        occ_nk = occ ^ king_bit
        while ka != 0
          t = ka.trailing_zeros_count
          ka &= ka - 1
          unless attacked_by?(t, them, occ_nk)
            out_ptr[count] = move(ksq, t)
            count += 1
          end
        end

        # everything except king moves is impossible in double check
        unless dbl_check
          {% if caps_only %}
            target_mask = them_occ
          {% else %}
            target_mask = ~us_occ
          {% end %}

          # --- knights --------------------------------------------------------
          pcs = pieces_of(us, KNIGHT) & ~pinned
          while pcs != 0
            s = pcs.trailing_zeros_count
            pcs &= pcs - 1
            atk = Tables.knight_attacks(s) & target_mask & check_mask
            while atk != 0
              t = atk.trailing_zeros_count
              atk &= atk - 1
              out_ptr[count] = move(s, t)
              count += 1
            end
          end

          # --- sliders ----------------------------------------------------------
          {% for pt in [BISHOP, ROOK, QUEEN] %}
            {% atk_expr =
                 pt == BISHOP ? "Tables.bishop_attacks(s, occ)".id :
               pt == ROOK   ? "Tables.rook_attacks(s, occ)".id :
                              "(Tables.bishop_attacks(s, occ) | Tables.rook_attacks(s, occ))".id %}
            # unpinned
            pcs = pieces_of(us, {{pt}}) & ~pinned
            while pcs != 0
              s = pcs.trailing_zeros_count
              pcs &= pcs - 1
              atk = {{atk_expr}} & target_mask & check_mask
              while atk != 0
                t = atk.trailing_zeros_count
                atk &= atk - 1
                out_ptr[count] = move(s, t)
                count += 1
              end
            end
            # pinned: may only slide along the pin line
            pcs = pieces_of(us, {{pt}}) & pinned
            while pcs != 0
              s = pcs.trailing_zeros_count
              pcs &= pcs - 1
              atk = {{atk_expr}} & Tables.line(ksq, s) & target_mask & check_mask
              while atk != 0
                t = atk.trailing_zeros_count
                atk &= atk - 1
                out_ptr[count] = move(s, t)
                count += 1
              end
            end
          {% end %}

          # --- pawns --------------------------------------------------------------
          {% for color in [0, 1] %}
          if us == {{color}}
            pp = pieces_of(us, PAWN)

            # pinned pawns: handled one by one against the pin line
            ppin = pp & pinned
            while ppin != 0
              s = ppin.trailing_zeros_count
              ppin &= ppin - 1
              allowed = Tables.line(ksq, s)
              {% if color == 0 %}
                fwd = s + 8
              {% else %}
                fwd = s - 8
              {% end %}
              fb = 1u64 << fwd
              if (fb & occ).zero? && (fb & allowed & check_mask) != 0
                {% if color == 0 %}
                  if fwd >= 56
                    emit_promos(s, fwd)
                  else
                    out_ptr[count] = move(s, fwd); count += 1
                    {% unless caps_only %}
                    if fwd < 24 # pawn stands on its second rank
                      f2 = fwd + 8
                      f2b = 1u64 << f2
                      if (f2b & occ).zero? && (f2b & allowed & check_mask) != 0
                        out_ptr[count] = move(s, f2); count += 1
                      end
                    end
                    {% end %}
                  end
                {% else %}
                  if fwd <= 7
                    emit_promos(s, fwd)
                  else
                    out_ptr[count] = move(s, fwd); count += 1
                    {% unless caps_only %}
                    if fwd >= 40 # pawn stands on its seventh rank
                      f2 = fwd - 8
                      f2b = 1u64 << f2
                      if (f2b & occ).zero? && (f2b & allowed & check_mask) != 0
                        out_ptr[count] = move(s, f2); count += 1
                      end
                    end
                    {% end %}
                  end
                {% end %}
              end
              pa = Tables.pawn_attacks({{color}}, s) & them_occ & allowed & check_mask
              while pa != 0
                t = pa.trailing_zeros_count
                pa &= pa - 1
                {% if color == 0 %}
                  if t >= 56
                    emit_promos(s, t)
                  else
                    out_ptr[count] = move(s, t); count += 1
                  end
                {% else %}
                  if t <= 7
                    emit_promos(s, t)
                  else
                    out_ptr[count] = move(s, t); count += 1
                  end
                {% end %}
              end
            end

            # free pawns: bitboard-parallel generation
            pfree = pp & ~pinned
            empty = ~occ
            {% if color == 0 %}
              one = (pfree << 8) & empty
              two = ((one & RANK_3_BB) << 8) & empty
              capl = ((pfree & ~FILE_A_BB) << 7) & them_occ
              capr = ((pfree & ~FILE_H_BB) << 9) & them_occ
              last_rank_bb = RANK_8_BB
            {% else %}
              one = (pfree >> 8) & empty
              two = ((one & RANK_6_BB) >> 8) & empty
              capl = ((pfree & ~FILE_A_BB) >> 9) & them_occ
              capr = ((pfree & ~FILE_H_BB) >> 7) & them_occ
              last_rank_bb = RANK_1_BB
            {% end %}

            {% unless caps_only %}
            qs = one & ~last_rank_bb & check_mask
            while qs != 0
              t = qs.trailing_zeros_count
              qs &= qs - 1
              {% if color == 0 %}
                out_ptr[count] = move(t - 8, t); count += 1
              {% else %}
                out_ptr[count] = move(t + 8, t); count += 1
              {% end %}
            end

            dt = two & check_mask
            while dt != 0
              t = dt.trailing_zeros_count
              dt &= dt - 1
              {% if color == 0 %}
                out_ptr[count] = move(t - 16, t); count += 1
              {% else %}
                out_ptr[count] = move(t + 16, t); count += 1
              {% end %}
            end
            {% end %}

            pr = one & last_rank_bb & check_mask
            while pr != 0
              t = pr.trailing_zeros_count
              pr &= pr - 1
              {% if color == 0 %}
                emit_promos(t - 8, t)
              {% else %}
                emit_promos(t + 8, t)
              {% end %}
            end

            cl = capl & ~last_rank_bb & check_mask
            while cl != 0
              t = cl.trailing_zeros_count
              cl &= cl - 1
              {% if color == 0 %}
                out_ptr[count] = move(t - 7, t); count += 1
              {% else %}
                out_ptr[count] = move(t + 9, t); count += 1
              {% end %}
            end

            cr = capr & ~last_rank_bb & check_mask
            while cr != 0
              t = cr.trailing_zeros_count
              cr &= cr - 1
              {% if color == 0 %}
                out_ptr[count] = move(t - 9, t); count += 1
              {% else %}
                out_ptr[count] = move(t + 7, t); count += 1
              {% end %}
            end

            clp = capl & last_rank_bb & check_mask
            while clp != 0
              t = clp.trailing_zeros_count
              clp &= clp - 1
              {% if color == 0 %}
                emit_promos(t - 7, t)
              {% else %}
                emit_promos(t + 9, t)
              {% end %}
            end

            crp = capr & last_rank_bb & check_mask
            while crp != 0
              t = crp.trailing_zeros_count
              crp &= crp - 1
              {% if color == 0 %}
                emit_promos(t - 9, t)
              {% else %}
                emit_promos(t + 7, t)
              {% end %}
            end
          end
          {% end %} # color loop
        end # unless dbl_check

        # --- en passant: always verified by full simulation --------------------
        #
        # Simulation covers every corner case (capturing a checking pawn, EP with
        # a pinned capturer, horizontal discovered checks after both pawns leave
        # the rank), so no pin/check special-casing is needed here.
        if @ep != NO_SQUARE
          eps = @ep.to_i
          cap_sq = us == WHITE ? eps - 8 : eps + 8
          cand = Tables.pawn_attacks(them, eps) & pieces_of(us, PAWN)
          base_kn = Tables.knight_attacks(ksq) & pieces_of(them, KNIGHT)
          base_pawn = Tables.pawn_attacks(us, ksq) & pieces_of(them, PAWN)
          base_king = Tables.king_attacks(ksq) & pieces_of(them, KING)
          while cand != 0
            s = cand.trailing_zeros_count
            cand &= cand - 1
            occ2 = (occ & ~((1u64 << s) | (1u64 << cap_sq))) | (1u64 << eps)
            if (Tables.bishop_attacks(ksq, occ2) & their_bq).zero? &&
               (Tables.rook_attacks(ksq, occ2) & their_rq).zero? &&
               base_kn.zero? &&
               (base_pawn & ~(1u64 << cap_sq)).zero? &&
               base_king.zero?
              out_ptr[count] = move_ep(s, eps)
              count += 1
            end
          end
        end

        # --- castling -----------------------------------------------------------
        {% unless caps_only %}
        if checkers.zero?
          {% for color in [0, 1] %}
          if us == {{color}}
            {% if color == 0 %}
            if (@castling & CASTLE_WK) != 0 && (occ & 0x0000000000000060u64).zero? &&
               !attacked_by?(5, them, occ) && !attacked_by?(6, them, occ)
              out_ptr[count] = move_castle(4, 6)
              count += 1
            end
            if (@castling & CASTLE_WQ) != 0 && (occ & 0x000000000000000Eu64).zero? &&
               !attacked_by?(3, them, occ) && !attacked_by?(2, them, occ)
              out_ptr[count] = move_castle(4, 2)
              count += 1
            end
            {% else %}
            if (@castling & CASTLE_BK) != 0 && (occ & 0x6000000000000000u64).zero? &&
               !attacked_by?(61, them, occ) && !attacked_by?(62, them, occ)
              out_ptr[count] = move_castle(60, 62)
              count += 1
            end
            if (@castling & CASTLE_BQ) != 0 && (occ & 0x0E00000000000000u64).zero? &&
               !attacked_by?(59, them, occ) && !attacked_by?(58, them, occ)
              out_ptr[count] = move_castle(60, 58)
              count += 1
            end
            {% end %}
          end
          {% end %}
        end
        {% end %}

        count
      end
    end

    define_gen(gen_legal, false)
    define_gen(gen_caps, true)

    # Debug helper: sorted list of UCI strings for the current position's legal moves.
    def legal_moves_string : String
      buf = Pointer(UInt16).malloc(MAX_MOVES)
      n = generate(buf)
      moves = Array(String).new(n)
      i = 0
      while i < n
        moves << mv_uci(buf[i])
        i += 1
      end
      moves.sort.join(" ")
    end

    # Find a legal move matching a UCI string (e.g. "e2e4", "e7e8q").
    def find_legal_uci(u : String) : UInt16?
      buf = Pointer(UInt16).malloc(MAX_MOVES)
      n = generate(buf)
      i = 0
      while i < n
        return buf[i] if mv_uci(buf[i]) == u
        i += 1
      end
      nil
    end
  end
end
