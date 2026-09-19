# UCI -> XBoard protocol bridge.
#
# Speaks UCI on stdin/stdout; drives an XBoard engine as a child process.
#
# Hard-won lessons baked in:
# - negotiate protover 2; reject optional features (SAN etc.) so engines emit
#   coordinate moves
# - fastchess never sends ucinewgame between games, and some engines (Crafty)
#   do not implement `new`: detect non-continuation positions and restart the
#   child; forward only the delta moves for continuations
# - convert UCI millisecond clocks to xboard centiseconds, using the
#   side-to-move's clock (wtime/btime), not always White's
# - discard stale engine moves from searches that outlived their game
# - resolve SAN replies (older Crafty) against a tracked shadow position,
#   with a structural fallback tolerant of disambiguation differences
#
# Usage: uci_bridge [--needs-restart] <xboard-engine-cmd> [args...]

require "process"
require "../../src/experion"

Experion.init_engine

module TrafficLog
  @@t0 : Time::Instant = Time.instant

  def self.<<(s : String)
    ms = ((Time.instant - @@t0).total_milliseconds * 10).to_i / 10
    File.write("/tmp/bridge_traffic.log", "#{ms}ms #{s}\n", mode: "a")
  end
end

lib CPoll
  struct Pollfd
    fd : LibC::Int
    events : LibC::Short
    revents : LibC::Short
  end

  fun poll(fds : Pollfd*, nfds : UInt32, timeout : LibC::Int) : LibC::Int
  fun read(fd : LibC::Int, buf : Void*, count : LibC::ULong) : LibC::Long
end

class Bridge
  POLLIN = 0x0001i16

  @cmd : String
  @args : Array(String)
  @proc : Process?
  @child_in : LibC::Int = -1
  @child_out : LibC::Int = -1
  @inbuf = Bytes.new(8192)
  @inlen = 0
  @childbuf = Bytes.new(65536)
  @childlen = 0
  @awaiting_move = false
  @shadow = Experion::Position.startpos
  @forwarded = [] of String
  @needs_restart : Bool
  @pending_reset = false
  @pending_moves = [] of String

  def initialize(cmd : String, args : Array(String), @needs_restart : Bool)
    @cmd = cmd
    @args = args
    spawn_child
  end

  def self.run(argv) : Nil
    needs_restart = false
    if argv[0]? == "--needs-restart"
      needs_restart = true
      argv = argv[1..]
    end
    new(argv[0], argv[1..], needs_restart).start
  end

  private def spawn_child : Nil
    old = @proc
    if old
      begin
        old.signal(Signal::KILL)
        old.wait
      rescue
      end
    end
    @proc = Process.new(@cmd, @args, input: :pipe, output: :pipe,
      error: File.open(File::NULL, "w"))
    @child_in = @proc.not_nil!.input.as(IO::FileDescriptor).fd
    @child_out = @proc.not_nil!.output.as(IO::FileDescriptor).fd
    @childlen = 0
    send_raw(@child_in, "xboard\nprotover 2\n")
  end

  def start : Nil
    loop do
      fds = StaticArray(CPoll::Pollfd, 2).new(CPoll::Pollfd.new(fd: 0, events: POLLIN, revents: 0i16))
      fds[1] = CPoll::Pollfd.new(fd: @child_out, events: POLLIN, revents: 0i16)
      n = CPoll.poll(fds.to_unsafe, 2, -1)
      next if n <= 0

      if (fds[0].revents & POLLIN) != 0
        r = CPoll.read(0, (@inbuf.to_unsafe + @inlen).as(Void*), @inbuf.size - @inlen)
        if r > 0
          @inlen += r.to_i32!
          @inlen = drain(@inbuf, @inlen) { |line| handle_uci(line) }
        elsif r == 0
          quit!
        end
      end

      if (fds[1].revents & POLLIN) != 0
        r = CPoll.read(@child_out, (@childbuf.to_unsafe + @childlen).as(Void*), @childbuf.size - @childlen)
        if r > 0
          @childlen += r.to_i32!
          @childlen = drain(@childbuf, @childlen) { |line| handle_child(line) }
        end
      end
    end
  end

  private def quit! : Nil
    p = @proc
    if p
      begin
        p.signal(Signal::KILL)
      rescue
      end
    end
    exit(0)
  end

  private def drain(buf : Bytes, len : Int32, &) : Int32
    consumed = 0
    i = 0
    while i < len
      if buf[i] == '\n'.ord
        yield String.new(buf[consumed...i]).strip
        consumed = i + 1
      end
      i += 1
    end
    rest = len - consumed
    (buf.to_unsafe + consumed).copy_to(buf.to_unsafe, rest) if rest > 0 && consumed > 0
    rest
  end

  private def send_raw(fd : LibC::Int, s : String) : Nil
    slice = s.to_slice
    LibC.write(fd, slice.to_unsafe.as(Void*), slice.size)
  end

  private def out(s : String) : Nil
    send_raw(1, s + "\n")
  end

  private def to_child(s : String) : Nil
    TrafficLog << "> " + s
    send_raw(@child_in, s + "\n")
  end

  private def handle_uci(line : String) : Nil
    TrafficLog << "> " + line
    tokens = line.split
    return if tokens.empty?
    case tokens[0]
    when "uci"
      out("id name XBoardBridge")
      out("uciok")
    when "isready"
      out("readyok")
    when "ucinewgame"
      @awaiting_move = false
      reset_child
    when "position"
      apply_position(tokens)
    when "go"
      # wtime is always present in a match, so `wtime || btime` used to
      # give Crafty White's clock on every move. As Black that is the
      # opponent's remaining time — a color bug, not an eval-sign bug.
      stm_white = @shadow.stm == Experion::WHITE.to_u8!
      my_key = stm_white ? "wtime" : "btime"
      opp_key = stm_white ? "btime" : "wtime"
      my = param(tokens, my_key) || param(tokens, opp_key)
      opp = param(tokens, opp_key) || param(tokens, my_key)

      # deliver buffered position changes only now — the child must not
      # think during book replay or between games
      if @pending_reset
        reset_child
        to_child("force")
        @pending_moves.each { |mv| to_child(mv) }
        if my
          safe = ((my.to_i? || 0) - 300).clamp(1, 10_000_000)
          to_child("time #{safe // 10}")
          to_child("otim #{(opp.to_i? || 0) // 10}") if opp
        end
        to_child("go")
      else
        @pending_moves.each { |mv| to_child(mv) }
        if my
          safe = ((my.to_i? || 0) - 300).clamp(1, 10_000_000)
          to_child("time #{safe // 10}")
          to_child("otim #{(opp.to_i? || 0) // 10}") if opp
        end
      end
      @pending_reset = false
      @pending_moves.clear
      @awaiting_move = true
    when "stop"
      to_child("?")
    when "quit"
      quit!
    end
  end

  # Reset the child to startpos. Engines that implement `new` get `new`;
  # others get a fresh process.
  private def reset_child : Nil
    # Crafty ignores `new` but boots in ~15ms, so a fresh process is the one
    # reliable reset; other engines just get `new`.
    if @needs_restart
      spawn_child
    else
      to_child("new")
      to_child("force")
    end
    @forwarded.clear
  end

  private def param(tokens : Array(String), key : String) : String?
    i = tokens.index(key)
    i && tokens[i + 1]?
  end

  private def apply_position(tokens : Array(String)) : Nil
    @awaiting_move = false

    if tokens.size >= 2 && tokens[1] == "fen"
      fen_end = tokens.index("moves") || tokens.size
      begin
        @shadow = Experion::Position.new(tokens[2...fen_end].join(" "))
      rescue
        return
      end
      TrafficLog << "! fen position unsupported"
      return
    end
    @shadow = Experion::Position.startpos

    moves_i = tokens.index("moves")
    move_tokens = moves_i ? tokens[(moves_i + 1)..] : [] of String

    continuation = !@forwarded.empty? &&
                   move_tokens.size >= @forwarded.size &&
                   (0...@forwarded.size).all? { |i| move_tokens[i]? == @forwarded[i] }
    delta_start = continuation ? @forwarded.size : 0

    if !continuation || (@forwarded.empty? && move_tokens.empty?)
      # divergent or new game: queue a full reset + complete replay
      @pending_reset = true
      @pending_moves = move_tokens.dup
      delta_start = 0
    else
      # normal continuation: buffer only the opponent's new move(s); they are
      # delivered when `go` arrives so the child does NOT auto-think during
      # the opening-book phase (that would burn real clock time)
      @pending_moves = move_tokens[delta_start..].dup
    end

    (delta_start...move_tokens.size).each do |i|
      mv = move_tokens[i]
      real = @shadow.find_legal_uci(mv)
      if real
        nxt = @shadow
        nxt.make_move(real.not_nil!, false)
        @shadow = nxt
      else
        TrafficLog << "! replay failed: #{mv}"
      end
    end
    @forwarded = move_tokens.dup
  end

  private def handle_child(line : String) : Nil
    TrafficLog << "< " + line
    if line.starts_with?("feature")
      name = line[7..].strip.split("=")[0]?.try(&.split(" ")[0])
      to_child("rejected #{name}") if name && !name.empty? && !name.in?("done")
      return
    end
    return unless line.starts_with?("move ")
    return unless @awaiting_move
    @awaiting_move = false

    given = line[5..].strip
    out("bestmove #{resolve(given)}")
  end

  # Coordinate moves pass through; SAN moves are matched against the tracked
  # position using the engine's own SAN generator.
  private def resolve(given : String) : String
    clean = given.gsub(/[+#!?]/, "")
    if clean.size >= 4 && clean[0].in?('a'..'h') && clean[1].in?('1'..'8') &&
       clean[2].in?('a'..'h') && clean[3].in?('1'..'8')
      nxt = @shadow
      real = nxt.find_legal_uci(clean)
      if real
        nxt.make_move(real.not_nil!, false)
        @shadow = nxt
      end
      return clean
    end

    buf = Pointer(UInt16).malloc(Experion::MAX_MOVES)
    n = @shadow.generate(buf)
    i = 0
    while i < n
      m = buf[i]
      if Experion::San.move_san(@shadow, m).gsub(/[+#!?]/, "") == clean ||
         Experion::Moves.mv_uci(m) == clean
        nxt = @shadow
        nxt.make_move(m, false)
        @shadow = nxt
        return Experion::Moves.mv_uci(m)
      end
      i += 1
    end

    fm = fuzzy_match(clean)
    if fm
      nxt = @shadow
      nxt.make_move(fm, false)
      @shadow = nxt
      return Experion::Moves.mv_uci(fm)
    end
    TrafficLog << "! unresolved SAN #{given} from #{@shadow.to_fen}"
    given
  end

  # Structural SAN match: [piece][disambig]x?target[=promo]; tolerates any
  # disambiguation style difference between engines.
  private def fuzzy_match(clean : String) : UInt16?
    s = clean
    ptype = Experion::PAWN
    if !s.empty? && "KQRBN".includes?(s[0])
      ptype = Experion::PIECE_CHAR.index(s[0]).not_nil! % 6
      s = s[1..]
    end
    promo = 0
    if idx = s.index('=')
      ps = s[(idx + 1)..][0]?
      return nil if ps.nil?
      up = ps.upcase
      promo = Experion::PIECE_CHAR.index(up) || return nil
      s = s[0...idx]
    elsif s.size == 5
      up = s[4].upcase
      promo = Experion::PIECE_CHAR.index(up) || return nil
      s = s[0...4]
    end
    return nil if s.size < 2
    tf = s[s.size - 2]
    tr = s[s.size - 1]
    return nil unless tf.in?('a'..'h') && tr.in?('1'..'8')
    target = (tr - '1') * 8 + (tf - 'a')

    matches = Array(UInt16).new
    buf = Pointer(UInt16).malloc(Experion::MAX_MOVES)
    n = @shadow.generate(buf)
    i = 0
    while i < n
      m = buf[i]
      if Experion::Moves.mv_to(m) == target &&
         @shadow.piece_at(Experion::Moves.mv_from(m)).to_i % 6 == ptype &&
         Experion::Moves.mv_promo_type(m) % 6 == promo % 6
        matches << m
      end
      i += 1
    end
    matches.size == 1 ? matches[0] : nil
  end
end

Bridge.run(ARGV)
