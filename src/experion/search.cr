# Alpha-beta search: iterative deepening, principal variation search,
# transposition table, null-move pruning, late move reductions, killer/history
# ordering, quiescence search, and repetition/50-move draw handling.
#
# Copy-make keeps state restoration trivial: each recursive call works on its
# own Position value; a parallel hash stack provides repetition detection
# across both game history and the live search path.

module Experion
  struct MoveEntry
    property move : UInt16
    property score : Int32

    def initialize(@move : UInt16, @score : Int32); end
  end

  class Limits
    property max_depth : Int32
    property soft_ms : Int64   # don't start a new iteration past this
    property hard_ms : Int64   # abort the search past this
    property nodes_max : UInt64
    property infinite : Bool

    def initialize
      @max_depth = MAX_PLY - 8
      @soft_ms = 0i64
      @hard_ms = 0i64
      @nodes_max = 0u64
      @infinite = false
    end
  end

  class Searcher
    include Moves

    INF = 1_000_000
    CAP_BASE     = 8_000_000
    QUEEN_PROMO  = 8_900_000
    KILLER_SCORE = 7_000_000
    HASH_SIZE    = 4096 # repetition/hash stack slots (game + search)
    KILLER_N     = 256  # MAX_PLY * 2
    COUNTER_N    = 4096 # from*64+to
    CONTHIST_N   = 49152 # prev_to(64) * piece(12) * to(64)
    HIST_N       = 768  # 12 piece codes * 64 target squares
    LMR_N        = 4096 # 64 * 64 reduction table
    FUTILITY     = StaticArray[0, 0, 200, 280, 450] # by depth (shallow-quiet margins)

    VICTIM = StaticArray[100, 300, 320, 500, 900, 10000, 0]

    getter tt, nodes
    property? verbose : Bool
    @last_score : Int32 = 0
    getter last_score : Int32

    # When true, info lines are written with raw LibC.write instead of
    # Crystal IO. Required when searching inside a bare Thread (no execution
    # context => Crystal IO raises).
    property? raw_output : Bool

    @tt : TT
    @stop : Atomic(Bool)
    @killers : StaticArray(UInt16, KILLER_N)
    @counters : StaticArray(UInt16, COUNTER_N)
    @conthist : Pointer(Int32)
    @history : StaticArray(Int32, HIST_N)
    @moves : Pointer(MoveEntry)
    @scratch : Pointer(UInt16)
    @hashes : Pointer(UInt64)
    @base_ply : Int32
    @nodes : UInt64
    @start_time : Time::Instant
    @seldepth : Int32
    @lmr : StaticArray(Int32, LMR_N)
    @root_pos : Position
    @accs : Pointer(Int32)
    @sevals : Pointer(Int32)
    @eval_cache : Pointer(UInt64) = Pointer(UInt64).malloc(2 * 262144)
    @eval_cache_mask : UInt64 = 262143u64

    def initialize(@tt : TT = TT.new, shared_stop : Atomic(Bool)? = nil,
                   worker_bias : Int32 = 0)
      @stop = shared_stop || Atomic(Bool).new(false)
      @killers = StaticArray(UInt16, KILLER_N).new(0u16)
      @counters = StaticArray(UInt16, COUNTER_N).new(0u16)
      @conthist = Pointer(Int32).malloc(CONTHIST_N)
      @history = StaticArray(Int32, HIST_N).new(0)
      @moves = Pointer(MoveEntry).malloc(MAX_MOVES * MAX_PLY)
      @scratch = Pointer(UInt16).malloc(MAX_MOVES)
      @hashes = Pointer(UInt64).malloc(HASH_SIZE)
      @accs = Pointer(Int32).malloc((MAX_PLY + 8) * Nnue.acc_row)
      @sevals = Pointer(Int32).malloc(MAX_PLY + 8)
      @base_ply = 0
      @nodes = 0u64
      @start_time = Time.instant
      @seldepth = 0
      @root_pos = Position.startpos
      @verbose = true
      @raw_output = false

      @lmr = StaticArray(Int32, LMR_N).new(0)
      d = 1
      while d < 64
        m = 1
        while m < 64
          r = (Math.log(d.to_f) * Math.log(m.to_f) / 2.3).to_i
          r = 0 if r < 0
          r = d - 2 if r > d - 2
          # worker diversity: odd workers reduce slightly more on late quiets,
          # giving lazy-SMP threads genuinely different trees
          if worker_bias > 0 && m > 6 && ((d + m) & 1) == 1
            r += 1
            r = d - 2 if r > d - 2
          end
          @lmr[d * 64 + m] = r
          m += 1
        end
        d += 1
      end
    end

    def new_game : Nil
      @tt.new_game
      @killers.fill(0u16)
      @history.fill(0)
      i = 0
      while i < CONTHIST_N
        @conthist[i] = 0
        i += 1
      end
    end

    # The stop flag, so SMP workers can share one with the primary searcher.
    def stop_atom : Atomic(Bool)
      @stop
    end

    def stop! : Nil
      @stop.set(true)
    end

    def stopped? : Bool
      @stop.get
    end

    # Compute NNUE accumulator for `child` (result of playing `m` on `pos`)
    # into row `child_ply`, based on row `parent_ply`. Call BEFORE make_move.
    private def push_acc(pos : Position, m : UInt16, parent_ply : Int32,
                         child_ply : Int32, child : Position) : Nil
      return unless Nnue.enabled?

      from = mv_from(m)
      to = mv_to(m)

      # castling moves three pieces: fall back to a full rebuild after make
      if pos.piece_at(from).to_i % 6 == KING && (from - to).abs == 2
        Nnue.refresh(@accs + child_ply * Nnue.acc_row, child)
        return
      end

      pc = pos.piece_at(from).to_i
      us = pos.stm.to_i
      is_ep = pc % 6 == PAWN && ((from ^ to) & 7) != 0 &&
              pos.piece_at(to) == NO_PIECE
      cap_sq = is_ep ? (us == WHITE ? to - 8 : to + 8) : to
      captured = pos.piece_at(cap_sq).to_i

      promo = mv_promo_type(m)
      placed = promo.zero? ? pc : (us * 6 + promo)

      rmw1 = Nnue.feature_index(pc, from, 0)
      rmb1 = Nnue.feature_index(pc, from, 1)
      addw = Nnue.feature_index(placed, to, 0)
      addb = Nnue.feature_index(placed, to, 1)

      if captured != NO_PIECE.to_i
        rmw2 = Nnue.feature_index(captured, cap_sq, 0)
        rmb2 = Nnue.feature_index(captured, cap_sq, 1)
        Nnue.apply_delta(@accs + child_ply * Nnue.acc_row,
          @accs + parent_ply * Nnue.acc_row,
          rmw1, rmb1, rmw2, rmb2, addw, addb, 0, 0, 2, 1)
      else
        Nnue.apply_delta(@accs + child_ply * Nnue.acc_row,
          @accs + parent_ply * Nnue.acc_row,
          rmw1, rmb1, 0, 0, addw, addb, 0, 0, 1, 1)
      end
    end

    # Copy accumulator unchanged across a null move.
    private def copy_acc(parent_ply : Int32, child_ply : Int32) : Nil
      return unless Nnue.enabled?
      (@accs + child_ply * Nnue.acc_row).copy_from(
        @accs + parent_ply * Nnue.acc_row, Nnue.acc_row)
    end

    private def evaluate_search(pos : Position, ply : Int32) : Int32
      h = pos.hash

      # eval cache: skip everything when position already evaluated
      idx = (h & @eval_cache_mask).to_i32!
      cached_hash = @eval_cache[idx * 2]
      if cached_hash == h
        raw = @eval_cache[idx * 2 + 1]
        v = (raw >> 1).to_i32!
        v = -v if (raw & 1) == 1
        return pos.stm == WHITE.to_u8! ? v : -v
      end

      v = Eval.evaluate(pos)

      # store white-POV value + sign bit
      wv = pos.stm == WHITE.to_u8! ? v : -v
      @eval_cache[idx * 2] = h
      @eval_cache[idx * 2 + 1] = wv.abs.to_u64! << 1 | (wv < 0 ? 1u64 : 0u64)

      v
    end

    private def elapsed_ms : Int64
      (Time.instant - @start_time).total_milliseconds.to_i64!
    end

    private def check_stop(limits : Limits) : Nil
      return if @nodes & 2047 != 0
      return if limits.infinite && limits.nodes_max.zero?
      @stop.set(true) if !limits.hard_ms.zero? && elapsed_ms >= limits.hard_ms
      @stop.set(true) if !limits.nodes_max.zero? && @nodes >= limits.nodes_max
    end

    # --- Lazy SMP entry ------------------------------------------------------------
    #
    # N searchers share one TT (lockless: 64-bit aligned stores make torn
    # entries merely look like misses) and one stop atom. Each worker runs a
    # full iterative search; the primary worker's move is used. Workers are
    # pure computation — no Crystal IO from these threads.

    def think_smp(root : Position, game_hashes : Array(UInt64), limits : Limits,
                  threads : Int32) : UInt16
      # SMP startup/join overhead dominates tiny budgets; scale down
      eff = threads
      if !limits.soft_ms.zero? && limits.soft_ms < 150 && eff > 2
        eff = 2
      end
      return think(root, game_hashes, limits) if eff <= 1

      shared_stop = Atomic(Bool).new(false)
      results = StaticArray(UInt16, 16).new(Moves::MOVE_NONE)
      done = Atomic(Int32).new(0)

      workers = Array(Thread).new(eff - 1)
      (1...eff).each do |i|
        workers << Thread.new do
          w = Searcher.new(@tt, shared_stop, i % 2 == 1 ? 1 : 0)
          w.verbose = false
          mv = w.think(root, game_hashes, limits)
          results[i] = mv
          done.add(1)
        end
      end

      # primary: this searcher, printing info as usual
      best = think(root, game_hashes, limits)
      results[0] = best
      shared_stop.set(true)
      workers.each(&.join)
      results.find { |m| m != Moves::MOVE_NONE } || Moves::MOVE_NONE
    end

    # --- public entry -------------------------------------------------------------

    # Returns the best move found; prints UCI info lines as iterations complete.
    def think(root : Position, game_hashes : Array(UInt64), limits : Limits) : UInt16
      raise "position history too long" if game_hashes.size + MAX_PLY > HASH_SIZE - 2

      @stop.set(false)
      @nodes = 0u64
      @start_time = Time.instant
      @killers.fill(0u16)
      @counters.fill(0u16)
      # decay (not clear) history so long-term evidence survives between moves
      hi = 0
      while hi < HIST_N
        @history[hi] >>= 1
        hi += 1
      end

      i = 0
      while i < game_hashes.size
        @hashes[i] = game_hashes[i]
        i += 1
      end
      @base_ply = game_hashes.size

      @root_pos = root
      pos = root
      @hashes[@base_ply] = pos.hash
      Nnue.refresh(@accs, pos) if Nnue.enabled?
      @sevals[0] = Eval.evaluate(pos)
      @sevals[1] = @sevals[0]
      @last_score = 0

      # root move list: order by simple MVV-LVA + center bias so the first
      # iteration's "best move" is more likely to actually be best
      root_count = pos.generate(@scratch)
      ri = 0
      while ri < root_count
        m = @scratch[ri]
        sc = 0
        victim = pos.piece_at(mv_to(m))
        if victim != NO_PIECE
          sc = CAP_BASE + VICTIM[victim.to_i % 6] * 16 -
               VICTIM[pos.piece_at(mv_from(m)).to_i % 6]
        elsif mv_promo_type(m) != 0
          sc = QUEEN_PROMO
        end
        # slight center bias for knight/bishop moves to e4/d4/e5/d5
        to = mv_to(m)
        if to == 27 || to == 28 || to == 35 || to == 36
          sc += 30
        end
        @moves[ri] = MoveEntry.new(m, sc)
        ri += 1
      end

      best_move = Moves::MOVE_NONE
      best_score = 0
      prev_score = 0
      last_completed = 0

      depth = 1
      while depth <= limits.max_depth
        @seldepth = 0
        alpha = -INF
        beta = INF

        if depth >= 5
          # scale delta with depth — deeper iterations vary more
          delta = 18 + depth
          alpha = prev_score - delta
          beta = prev_score + delta
          loop do
            score = search_root(pos, root_count, depth, alpha, beta, limits)
            break if @stop.get
            if score <= alpha
              alpha = score - delta
              delta += delta
            elsif score >= beta
              beta = score + delta
              delta += delta
            else
              best_score = score
              break
            end
            if alpha < -INF
              alpha = -INF
            end
            if beta > INF
              beta = INF
            end
          end
        else
          best_score = search_root(pos, root_count, depth, -INF, INF, limits)
        end

        break if @stop.get

        last_completed = depth
        best_move = @moves[0].move
        prev_score = best_score
        print_info(depth, best_score)
        @tt.bump_age

        break if best_score.abs > Eval::MATE_IN_MAX

        unless limits.infinite
          # spend most of the budget on the current iteration; start a new one
          # only if comfortably inside the soft window
          break if !limits.soft_ms.zero? && elapsed_ms * 4 >= limits.soft_ms * 3
        end

        depth += 1
      end

      if best_move == Moves::MOVE_NONE && root_count > 0
        best_move = @moves[0].move
      end
      @last_score = best_score
      best_move
    end

    # --- root ----------------------------------------------------------------------

    private def search_root(pos : Position, count : Int32, depth : Int32,
                            alpha : Int32, beta : Int32, limits : Limits) : Int32
      a = alpha
      best = -INF
      legal = 0
      i = 0
      while i < count
        m = @moves[i].move

        child = pos
        push_acc(pos, m, 0, 1, child)
        child.make_move(m)
        @hashes[@base_ply + 1] = child.hash
        legal += 1

        gives_check = child.in_check?
        if legal == 1
          score = -negamax(child, depth - 1, -beta, -a, 1, limits, true)
        else
          r = 0
          if depth >= 3 && legal > 3 &&
             child.piece_at(mv_to(m)) == NO_PIECE && mv_promo_type(m) == 0 && !gives_check
            r = @lmr[depth.clamp(0, 63) * 64 + legal.clamp(0, 63)]
            r = depth - 2 if r > depth - 2
            r = 0 if r < 0
          end
          score = -negamax(child, depth - 1 - r, -a - 1, -a, 1, limits, true)
          if score > a && r > 0
            score = -negamax(child, depth - 1, -a - 1, -a, 1, limits, true)
          end
          if score > a && score < beta
            score = -negamax(child, depth - 1, -beta, -a, 1, limits, true)
          end
        end

        @moves[i] = MoveEntry.new(m, score) # remembered for next-iteration ordering

        if score > best
          best = score
          if score > a
            a = score
            break if a >= beta
          end
        end
        break if @stop.get
        i += 1
      end

      # stable sort SEARCHED moves by score desc; unsearched moves (default
      # score 0) keep their original generator order. We only sort up to
      # `legal` (count of moves actually searched), so unsearched tail moves
      # with score 0 don't bubble above real scores.
      i2 = 1
      while i2 < legal
        e = @moves[i2]
        j = i2 - 1
        while j >= 0 && @moves[j].score < e.score
          @moves[j + 1] = @moves[j]
          j -= 1
        end
        @moves[j + 1] = e
        i2 += 1
      end
      best
    end

    # --- main search ---------------------------------------------------------------

    private def negamax(pos : Position, depth : Int32, alpha : Int32, beta : Int32,
                        ply : Int32, limits : Limits, can_null : Bool,
                        prev_m : UInt16 = Moves::MOVE_NONE) : Int32
      a = alpha
      b = beta
      @nodes += 1
      @seldepth = ply if ply > @seldepth
      check_stop(limits)
      return 0 if @stop.get

      # mate distance pruning
      a = -Eval::MATE + ply if a < -Eval::MATE + ply
      b = Eval::MATE - ply - 1 if b > Eval::MATE - ply - 1
      return a if a >= b

      # draws
      return 0 if repetition?(pos, ply)
      return 0 if pos.halfmove >= 100
      return 0 if Eval.insufficient_material?(pos)

      us = pos.stm.to_i
      in_check = pos.in_check?
      # bounded check extension: the ply cap guarantees termination on
      # perpetual-check lines
      depth += 1 if in_check && depth >= 1 && ply < 32



      if depth <= 0
        return qsearch(pos, a, b, ply, limits, !in_check)
      end

      # TT probe
      tt_hit, tt_move, tt_score, tt_depth, tt_flags = @tt.probe(pos.hash)
      if tt_hit && tt_depth >= depth
        s = @tt.score_from_tt(tt_score, ply)
        if (tt_flags == TT::FLAG_EXACT) ||
           (tt_flags == TT::FLAG_LOWER && s >= b) ||
           (tt_flags == TT::FLAG_UPPER && s <= a)
          return s
        end
      end
      tt_move = Moves::MOVE_NONE if tt_move == 0u16

      # --- Singular Extensions ----------------------------------------------
      # If the TT move has enough depth and a non-mate score, do a quick
      # verification search to see if it's MUCH better than all alternatives.
      # If singular, extend the TT move's search by 1 ply (or 2 for double).
      singular_ext = 0
      if tt_hit && tt_move != Moves::MOVE_NONE && depth >= 6 && !in_check &&
         tt_score.abs < Eval::MATE_IN_MAX && (tt_flags == TT::FLAG_EXACT || tt_flags == TT::FLAG_LOWER)
        # do a reduced-depth search excluding the TT move; if no alternative
        # can match the TT score minus a margin, the move is singular
        verify_beta = tt_score - 2 * depth
        if verify_beta > -Eval::MATE_IN_MAX && verify_beta < b
          # search all moves except tt_move at reduced depth with verify_beta
          singular = singular_check(pos, ply, tt_move, depth - 1, verify_beta, limits, prev_m)
          if singular
            singular_ext = 1
            # double extension: if the original TT depth is much higher than
            # ours, we trust the TT more, allow a second extension
            singular_ext = 2 if tt_depth >= depth + 3
          elsif !singular.nil? && tt_score <= alpha
            # multi-cut: if even the best alternative falls well below alpha,
            # we can prune
            return tt_score
          end
        end
      end

      # internal iterative reduction: without a hash move, search one ply
      # less — the IIR is cheaper than IID and gives most of the benefit.
      depth -= 1 if tt_move == Moves::MOVE_NONE && depth >= 5 && !in_check

      depth += singular_ext

      static_eval = evaluate_search(pos, ply)
      @sevals[ply] = static_eval

      # "improving": our static eval is better than it was two plies ago
      improving = ply >= 2 && @sevals[ply] > @sevals[ply - 2]

      # reverse futility pruning
      if !in_check && depth <= 4 && static_eval - 80 * depth >= b &&
         b.abs < Eval::MATE_IN_MAX
        return static_eval
      end

      # null move pruning (need non-pawn material to avoid zugzwang blindness)
      non_pawn = pos.occ_of(us) & ~(pos.pieces_of(us, PAWN) | pos.pieces_of(us, KING))
      if can_null && !in_check && depth >= 3 && static_eval >= b &&
         non_pawn != 0 && b.abs < Eval::MATE_IN_MAX
        np = pos
        copy_acc(ply, ply + 1)
        np.make_null_move
        @hashes[@base_ply + ply + 1] = np.hash
        r = 2 + depth // 5
        r += 1 if depth > 7
        score = -negamax(np, depth - 1 - r, -b, -b + 1, ply + 1, limits, false)
        return b if score >= b && score.abs < Eval::MATE_IN_MAX
      end

      count = generate_into(pos, ply)
      score_moves(pos, ply, count, tt_move, prev_m)

      best = -INF
      best_move = Moves::MOVE_NONE
      legal = 0
      old_a = a
      i = 0
      while i < count
        m = pick_best(ply, count, i)

        pc = pos.piece_at(mv_from(m)).to_i
        quiet = pos.piece_at(mv_to(m)) == NO_PIECE && mv_promo_type(m) == 0

        # recapture extension: capturing on the previously-contested square
        recapture = !quiet && prev_m != Moves::MOVE_NONE &&
                    mv_to(m) == mv_to(prev_m) && ply < 32

        # futility pruning: hopeless quiets and clearly-losing captures
        prune_futility = false
        if !in_check && legal >= 1 && b.abs < Eval::MATE_IN_MAX
          if quiet
            prune_futility = true if depth <= 2 &&
                                    static_eval + FUTILITY[depth] <= a
          else
            # SEE-based capture pruning: skip clearly-losing captures
            # (and quiet captures via SEE up to depth 6)
            see_val = See.see(pos, m)
            prune_futility = true if depth <= 4 && see_val < -(80 * depth)
            # at higher depths, prune only very negative captures
            prune_futility = true if depth <= 6 && see_val < -300
          end
        end

        # late move pruning: at very low depth, very late quiets are almost
        # never the best move. Aggressive pruning hurts in tactical lines.
        prune_lmp = false
        if !in_check && quiet && depth <= 2 && b.abs < Eval::MATE_IN_MAX
          lmp_margin = if depth == 1
                        4
                      else
                        6
                      end
          lmp_margin -= 1 if improving
          prune_lmp = true if legal > lmp_margin
        end

        unless prune_futility || prune_lmp
          child = pos
          push_acc(pos, m, ply, ply + 1, child)
          child.make_move(m)
          @hashes[@base_ply + ply + 1] = child.hash
          legal += 1

          gives_check = child.in_check?
          score = 0

          dchild = depth - 1 + (recapture ? 1 : 0)
          if legal == 1
            score = -negamax(child, dchild, -b, -a, ply + 1, limits, true, m)
          else
            r = 0
            if depth >= 3 && legal > 3 && quiet && !in_check && !gives_check
              r = @lmr[depth.clamp(0, 63) * 64 + legal.clamp(0, 63)]
              h = @history[pc * 64 + mv_to(m)]
              r -= 1 if pc // 6 != PAWN && h > 4000
              r += 1 if legal > 6 && h < 80
              r = depth - 2 if r > depth - 2
              r = 0 if r < 0
            end
            score = -negamax(child, dchild - r, -a - 1, -a, ply + 1, limits, true, m)
            if score > a && r > 0
              score = -negamax(child, dchild, -a - 1, -a, ply + 1, limits, true, m)
            end
            if score > a && score < b
              score = -negamax(child, dchild, -b, -a, ply + 1, limits, true, m)
            end
          end

          if score > best
            best = score
            best_move = m
            if score > a
              a = score
              if a >= b
                if quiet
                  save_killer(ply, m)
                  bump_history(pc, mv_to(m), depth)
                  if prev_m != Moves::MOVE_NONE
                    @counters[mv_from(prev_m) * 64 + mv_to(prev_m)] = m
                    chi = mv_to(prev_m) * 768 + pc * 64 + mv_to(m)
                    v = @conthist[chi] + depth * depth
                    @conthist[chi] = v > 8_000_000 ? 8_000_000 : v
                  end
                end
                break
              end
            end
          end
        else
          # searched quiet that didn't cut: penalize so it sinks in the
          # ordering on this and future searches
          if quiet
            bump_history_down(pc, mv_to(m), depth)
            if prev_m != Moves::MOVE_NONE
              chi = mv_to(prev_m) * 768 + pc * 64 + mv_to(m)
              v = @conthist[chi] - depth * depth
              @conthist[chi] = v < -8_000_000 ? -8_000_000 : v
            end
          end
        end

        i += 1
      end

      if legal.zero?
        return in_check ? -Eval::MATE + ply : 0
      end

      return best if @stop.get

      flags = if best >= b
                TT::FLAG_LOWER
              elsif best <= old_a
                TT::FLAG_UPPER
              else
                TT::FLAG_EXACT
              end
      @tt.store(pos.hash, best_move, @tt.score_to_tt(best, ply), depth, flags)
      best
    end

    # --- quiescence ------------------------------------------------------------------

    private def qsearch(pos : Position, alpha : Int32, beta : Int32, ply : Int32,
                        limits : Limits, gen_checks : Bool = false) : Int32
      @nodes += 1
      @seldepth = ply if ply > @seldepth
      check_stop(limits)
      return 0 if @stop.get

      in_check = pos.in_check?

      if ply >= MAX_PLY - 2
        return evaluate_search(pos, ply)
      end

      # qsearch TT probe
      q_hit, q_move, q_score, q_depth, q_flags = @tt.probe(pos.hash)
      if q_hit && q_depth >= 0
        qs = @tt.score_from_tt(q_score, ply)
        if (q_flags == TT::FLAG_EXACT) ||
           (q_flags == TT::FLAG_LOWER && qs >= beta) ||
           (q_flags == TT::FLAG_UPPER && qs <= alpha)
          return qs
        end
      end

      buf = move_ptr(ply)
      count = in_check ? pos.generate(@scratch) : pos.generate_captures(@scratch)
      ci = 0
      while ci < count
        buf[ci] = MoveEntry.new(@scratch[ci], 0)
        ci += 1
      end

      if in_check
        # no stand-pat in check; mate/stalemate decided by legal replies
        best = -INF
        legal = 0
        i = 0
        # order evasions lightly: captures first
        while i < count
          m = buf[i].move
          victim = pos.piece_at(mv_to(m))
          sc = victim == NO_PIECE ? 0 : CAP_BASE + VICTIM[victim.to_i % 6]
          buf[i] = MoveEntry.new(m, sc)
          i += 1
        end
        i = 0
        while i < count
          m = pick_best_q(buf, count, i)
          child = pos
          push_acc(pos, m, ply, ply + 1, child)
          child.make_move(m)
          @hashes[@base_ply + ply + 1] = child.hash
          legal += 1
          score = -qsearch(child, -beta, -alpha, ply + 1, limits)
          if score > best
            best = score
            if score > alpha
              alpha = score
              break if alpha >= beta
            end
          end
          i += 1
        end
        return legal.zero? ? -Eval::MATE + ply : best
      end

      stand = evaluate_search(pos, ply)
      return stand if stand >= beta
      a = stand > alpha ? stand : alpha
      alpha0 = alpha
      best_move = Moves::MOVE_NONE

      i = 0
      while i < count
        m = buf[i].move
        pt = mv_promo_type(m)
        if pt == QUEEN
          sc = QUEEN_PROMO
        else
          # SEE drives both ordering and pruning here
          v = See.see(pos, m)
          sc = v > 0 ? CAP_BASE + v : CAP_BASE // 2 + v
          sc += 400_000 if pt != 0
        end
        buf[i] = MoveEntry.new(m, sc)
        i += 1
      end

      # first quiescence ply also considers checking moves
      check_count = count
      if gen_checks && ply < 40
        all_count = pos.generate(@scratch)
        j = 0
        while j < all_count
          m = @scratch[j]
          child = pos
          child.make_move(m)
          if child.in_check?(child.stm.to_i ^ 1)
            buf[check_count] = MoveEntry.new(m, QUEEN_PROMO + 100)
            check_count += 1
          end
          j += 1
        end
      end

      best = stand
      i = 0
      while i < check_count
        m = pick_best_q(buf, check_count, i)
        i += 1

        prune = false
        unless mv_promo_type(m) != 0 && pos.piece_at(mv_to(m)) == NO_PIECE
          # captures were already SEE-scored: negative score => losing capture
          if pos.piece_at(mv_to(m)) != NO_PIECE && mv_promo_type(m) != QUEEN
            prune = true if See.see(pos, m) < 0
            unless prune
              victim = VICTIM[pos.piece_at(mv_to(m)).to_i % 6]
              prune = true if stand + victim + 220 <= alpha # delta pruning
            end
          end
        end

        unless prune
          child = pos
          push_acc(pos, m, ply, ply + 1, child)
          child.make_move(m)
          @hashes[@base_ply + ply + 1] = child.hash

          score = -qsearch(child, -beta, -a, ply + 1, limits)
          if score > best
            best = score
            best_move = m
            if score > a
              a = score
              break if a >= beta
            end
          end
        end
      end

      return best if @stop.get
      flags = if best >= beta
                TT::FLAG_LOWER
              elsif best <= alpha0
                TT::FLAG_UPPER
              else
                TT::FLAG_EXACT
              end
      @tt.store(pos.hash, best_move, @tt.score_to_tt(best, ply), 0, flags)
      best
    end

    # --- helpers -----------------------------------------------------------------------

    @[AlwaysInline]
    private def move_ptr(ply : Int32) : Pointer(MoveEntry)
      @moves + ply * MAX_MOVES
    end

    private def generate_into(pos : Position, ply : Int32) : Int32
      n = pos.generate(@scratch)
      buf = move_ptr(ply)
      i = 0
      while i < n
        buf[i] = MoveEntry.new(@scratch[i], 0)
        i += 1
      end
      n
    end

    private def score_moves(pos : Position, ply : Int32, count : Int32, tt_move : UInt16,
                            prev_m : UInt16 = Moves::MOVE_NONE) : Nil
      buf = move_ptr(ply)
      i = 0
      while i < count
        m = buf[i].move
        sc = 0
        if m == tt_move
          sc = 9_000_000
        else
          pt = mv_promo_type(m)
          victim = pos.piece_at(mv_to(m))
          if victim != NO_PIECE
            sc = CAP_BASE + VICTIM[victim.to_i % 6] * 16 - VICTIM[pos.piece_at(mv_from(m)).to_i % 6]
            sc += QUEEN_PROMO - CAP_BASE if pt == QUEEN
          elsif pt == QUEEN
            sc = QUEEN_PROMO
          elsif m == @killers[ply * 2]
            sc = KILLER_SCORE
          elsif m == @killers[ply * 2 + 1]
            sc = KILLER_SCORE - 1
          elsif prev_m != Moves::MOVE_NONE &&
                m == @counters[mv_from(prev_m) * 64 + mv_to(prev_m)]
            sc = KILLER_SCORE - 2
          else
            h = @history[pos.piece_at(mv_from(m)).to_i * 64 + mv_to(m)]
            if prev_m != Moves::MOVE_NONE
              ch = @conthist[mv_to(prev_m) * 768 +
                             pos.piece_at(mv_from(m)).to_i * 64 + mv_to(m)]
              h += ch
            end
            h = h * 4 if h > 0 # amplify positive history relative to killers
            h = 0 if h < 0
            sc = h < 5_000_000 ? h : 5_000_000
          end
          sc += 500_000 if pt != 0
        end
        buf[i] = MoveEntry.new(m, sc)
        i += 1
      end
    end

    private def pick_best(ply : Int32, count : Int32, i : Int32) : UInt16
      buf = move_ptr(ply)
      best_i = i
      best_s = buf[i].score
      j = i + 1
      while j < count
        if buf[j].score > best_s
          best_s = buf[j].score
          best_i = j
        end
        j += 1
      end
      if best_i != i
        tmp = buf[i]
        buf[i] = buf[best_i]
        buf[best_i] = tmp
      end
      buf[i].move
    end

    private def pick_best_q(buf : Pointer(MoveEntry), count : Int32, i : Int32) : UInt16
      best_i = i
      best_s = buf[i].score
      j = i + 1
      while j < count
        if buf[j].score > best_s
          best_s = buf[j].score
          best_i = j
        end
        j += 1
      end
      if best_i != i
        tmp = buf[i]
        buf[i] = buf[best_i]
        buf[best_i] = tmp
      end
      buf[i].move
    end

    private def save_killer(ply : Int32, m : UInt16) : Nil
      k0 = @killers[ply * 2]
      if k0 != m
        @killers[ply * 2 + 1] = k0
        @killers[ply * 2] = m
      end
    end

    # Returns true if the tt_move is "singular": no other move can match
    # verify_beta at reduced depth. Returns false if any alternative beats it.
    # Returns nil if a TT cutoff was hit (no clear answer — fall through).
    private def singular_check(pos : Position, ply : Int32, skip : UInt16,
                               depth : Int32, beta : Int32, limits : Limits,
                               prev_m : UInt16) : Bool?
      a = beta - 1
      count = generate_into(pos, ply)
      score_moves(pos, ply, count, Moves::MOVE_NONE, prev_m)
      i = 0
      while i < count
        m = pick_best(ply, count, i)
        i += 1
        next if m == skip
        child = pos
        push_acc(pos, m, ply, ply + 1, child)
        child.make_move(m)
        @hashes[@base_ply + ply + 1] = child.hash
        score = -negamax(child, depth, -beta, -a, ply + 1, limits, true, m)
        if score >= beta
          return false # a non-skip move beats beta
        end
        return nil if @stop.get
      end
      true
    end

    private def bump_history(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      v = @history[idx] + depth * depth
      @history[idx] = v > 8_000_000 ? 8_000_000 : v
    end

    private def bump_history_down(pc : Int, to : Int, depth : Int32) : Nil
      idx = pc * 64 + to
      v = @history[idx] - depth * depth
      @history[idx] = v < -8_000_000 ? -8_000_000 : v
    end

    private def repetition?(pos : Position, ply : Int32) : Bool
      cur = @base_ply + ply
      lo = cur - pos.halfmove.to_i
      lo = 0 if lo < 0
      i = cur - 2
      while i >= lo
        return true if @hashes[i] == pos.hash
        i -= 2
      end
      false
    end

    private def print_info(depth : Int32, score : Int32) : Nil
      return unless @verbose
      ms = elapsed_ms
      nps = ms > 0 ? @nodes * 1000 // ms : @nodes
      pv = pv_string
      score_str = if score.abs > Eval::MATE_IN_MAX
                    plies = Eval::MATE - score.abs
                    moves = (plies + 1) // 2
                    score > 0 ? "mate #{moves}" : "mate -#{moves}"
                  else
                    "cp #{score}"
                  end
      line = "info depth #{depth} seldepth #{@seldepth} score #{score_str} nodes #{@nodes} nps #{nps} time #{ms} pv #{pv}\n"
      if @raw_output
        Raw.write_stdout(line)
      else
        puts line.chomp
        STDOUT.flush
      end
    end

    def pv_string : String
      parts = Array(String).new
      pos = @root_pos
      seen = Set(UInt64).new
      seen << pos.hash
      while parts.size < 24
        hit, m, s, d, f = @tt.probe(pos.hash)
        break if !hit || m == Moves::MOVE_NONE
        # validate against real legal moves
        found : UInt16? = nil
        n = pos.generate(@scratch)
        i = 0
        while i < n
          if @scratch[i] == m
            found = m
            break
          end
          i += 1
        end
        break if found.nil?
        parts << Moves.mv_uci(found.not_nil!)
        child = pos
        child.make_move(found.not_nil!, false)
        break if seen.includes?(child.hash)
        seen << child.hash
        pos = child
      end
      parts.join(" ")
    end
  end

  # Minimal stdout writer safe to call from a bare Thread.
  module Raw
    def self.write_stdout(s : String) : Nil
      slice = s.to_slice
      LibC.write(1, slice.to_unsafe.as(Void*), slice.size)
    end
  end
end

module Experion
  module See
    extend self
    include Moves

    VAL = StaticArray[100, 300, 320, 500, 900, 10000, 0]

    # Static exchange evaluation via the swap algorithm. Returns the material
    # balance (from `side`'s perspective... convention: gain for the side that
    # captures first) of the capture sequence initiated by move `m`.
    #
    # X-ray awareness: sliders recapture "through" vacated squares because the
    # occupancy is updated per iteration and slider attacks recomputed lazily.
    def see(pos : Position, m : UInt16) : Int32
      from = mv_from(m)
      to = mv_to(m)

      target = pos.piece_at(to)
      value = if target != NO_PIECE
                VAL[target.to_i % 6]
              else
                100 # en passant
              end

      attacker_pc = pos.piece_at(from).to_i
      gain = StaticArray(Int32, 32).new(0)
      gain[0] = value

      occ = pos.occ_all
      occ &= ~(1u64 << from)
      if target == NO_PIECE && pos.piece_at(from).to_i % 6 == PAWN
        # en passant: captured pawn is behind the target square
        cap_sq = pos.stm == WHITE.to_u8! ? to - 8 : to + 8
        occ &= ~(1u64 << cap_sq)
      end

      # attackers sets, updated as pieces are removed
      side = pos.stm.to_i ^ 1 # opponent to move (recapture side)
      bishops = pos.pieces_of(0, BISHOP) | pos.pieces_of(0, QUEEN) |
                pos.pieces_of(1, BISHOP) | pos.pieces_of(1, QUEEN)
      rooks = pos.pieces_of(0, ROOK) | pos.pieces_of(0, QUEEN) |
              pos.pieces_of(1, ROOK) | pos.pieces_of(1, QUEEN)
      knights = pos.pieces_of(0, KNIGHT) | pos.pieces_of(1, KNIGHT)
      kings = pos.pieces_of(0, KING) | pos.pieces_of(1, KING)
      pawns = pos.pieces_of(0, PAWN) | pos.pieces_of(1, PAWN)

      attacker_val = VAL[attacker_pc % 6]
      d = 0
      while true
        d += 1
        gain[d] = attacker_val - gain[d - 1]

        # find least valuable attacker of `to` for `side`
        atk_sq = least_attacker(pos, to, side, occ, pawns, knights, bishops, rooks, kings)
        break if atk_sq < 0

        pc = pos.piece_at(atk_sq).to_i
        attacker_val = VAL[pc % 6]

        occ &= ~(1u64 << atk_sq)
        side ^= 1
        break if d > 30
      end

      # walk back accumulating
      while d > 1
        d -= 1
        gain[d - 1] = -(Math.max(-gain[d - 1], gain[d]))
      end
      gain[0]
    end

    private def least_attacker(pos : Position, to : Int32, side : Int32,
                               occ : UInt64, pawns : UInt64, knights : UInt64,
                               bishops : UInt64, rooks : UInt64, kings : UInt64) : Int32
      # pawn
      atk = Tables.pawn_attacks(side ^ 1, to) & pawns & pos.occ_of(side) & occ
      return atk.trailing_zeros_count.to_i! unless atk.zero?
      # knight
      atk = Tables.knight_attacks(to) & knights & pos.occ_of(side) & occ
      return atk.trailing_zeros_count.to_i! unless atk.zero?
      # bishop/queen diagonal
      b_atk = Tables.bishop_attacks(to, occ)
      atk = b_atk & bishops & pos.occ_of(side) & occ
      return atk.trailing_zeros_count.to_i! unless atk.zero?
      # rook/queen straight
      r_atk = Tables.rook_attacks(to, occ)
      atk = r_atk & rooks & pos.occ_of(side) & occ
      return atk.trailing_zeros_count.to_i! unless atk.zero?
      # king
      atk = Tables.king_attacks(to) & kings & pos.occ_of(side) & occ
      return atk.trailing_zeros_count.to_i! unless atk.zero?
      -1
    end
  end
end
