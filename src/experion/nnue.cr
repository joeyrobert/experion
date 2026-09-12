# ENN4 is the current color-preserving, incrementally evaluated network.
# Train with tools/train_nnue_v4.py; see load_v4/evaluate_v4 below for its
# format. ENN3 remains loadable for comparison with historical checkpoints.
# The following format notes describe that legacy architecture only.
#
# NNUE evaluation.
#
# Mirrors tools/nnue_train.py exactly:
#   features : king-bucketed HalfKA. Each perspective's own king square picks
#              a bucket (file quadrant, KING_BUCKETS=4: a-b/c-d/e-f/g-h) and
#              ALL of that perspective's piece features are offset into that
#              bucket's block: idx = bucket*1536 + slot*768 + ptype*64 + rel.
#              This lets the net learn different piece-square values depending
#              on which side of the board its own king sits on — the flat
#              (unbucketed) HalfKA net could not express this at all, which
#              measurement (STS: 32.4% classical vs 6.8% pure NNUE) pointed to
#              as the main remaining positional-judgment gap. See
#              docs/nnue-session-findings.md.
#   w1       : (1536*KING_BUCKETS) x H int16, feature-major (feature*H + h)
#   acc      : int32[H] per perspective, plain sum of w1 rows
#   act      : clamp(acc_w[h] + acc_b[h], -512, 512)                [a, per h]
#   hidden   : clamp((a . wh[:,j] + bh[j]) >> WH_SHIFT, 0, 512)     [per j]
#   out_c    : (hidden . w2[c]) >> W2_SHIFT
#   eval cp  : (blend(out_mg, out_eg) * 600) >> 9
#
# File format "ENN3": magic(4) H(4) HID(4) wh_shift(4) w2_shift(4)
# king_buckets(4) then w1(1536*KING_BUCKETS*H int16), wh(H*HID int16),
# bh(HID int16), w2(2*HID int16).
# wh_shift/w2_shift are chosen per-export from the ACTUAL trained weight
# magnitudes (see nnue_train.py's pick_shift) — a fixed shift picked in the
# abstract (the original OUT_SHIFT=20) silently overflowed int16 by ~70x for
# hours earlier this session before being caught by a direct sanity check
# against known positions. Never hardcode a shift here without that check.
#
# CRITICAL: because a perspective's own king square selects its entire
# feature block, moving that king changes every one of that perspective's
# feature indices, not just the king's own. Any king move (not just castling)
# therefore forces a full accumulator rebuild via `refresh` — incremental
# `apply_delta` is only valid when neither side's king moves. See push_acc in
# search.cr.
#
# The accumulator lives in the searcher's stack (one 2*H row per ply); make
# sites update it incrementally via `apply_delta`.

@[Link("c")]
lib LibMemory
  fun memcpy(dest : Void*, src : Void*, n : LibC::SizeT) : Void*
end

module Experion
  module Nnue
    extend self

    @@w1 : Pointer(Int16)? = nil
    @@wh : Pointer(Int16)? = nil
    @@bh : Pointer(Int16)? = nil
    @@w2 : Pointer(Int16)? = nil
    @@enabled = false
    @@disabled_by_option = false
    @@blend = 100
    @@h : Int32 = 256        # hidden accumulator width from the loaded file
    @@hid : Int32 = 32       # second hidden layer width from the loaded file
    @@wh_shift : Int32 = 0
    @@w2_shift : Int32 = 0
    @@acc_row : Int32 = 512  # 2 * h
    @@king_buckets : Int32 = 1
    @@v4 = false
    @@bias : Pointer(Int16)? = nil
    FEATURES_PER_BUCKET = 1536

    def self.h : Int32
      @@h
    end

    def self.acc_row : Int32
      @@acc_row
    end

    def self.enabled? : Bool
      @@enabled && !@@disabled_by_option
    end

    def self.set_option(on : Bool) : Nil
      @@disabled_by_option = !on
    end

    # 0 = pure classical, 100 = pure NNUE
    def self.blend : Int32
      @@blend
    end

    def self.set_blend(pct : Int32) : Nil
      @@blend = pct.clamp(0, 100)
    end

    def self.w1_ptr : Pointer(Int16)
      @@w1.not_nil!
    end

    def self.load(path : String) : Bool
      begin
        data = File.read(path)
      rescue
        @@enabled = false
        return false
      end
      return load_v4(data) if data.size >= 8 && data[0, 4] == "ENN4"
      return false unless data.size > 24 && data[0, 4] == "ENN3"

      h = IO::Memory.new(data)
      hdr = Bytes.new(24)
      h.read_fully(hdr)
      hh = IO::ByteFormat::LittleEndian.decode(Int32, hdr[4, 4])
      hid = IO::ByteFormat::LittleEndian.decode(Int32, hdr[8, 4])
      wh_shift = IO::ByteFormat::LittleEndian.decode(Int32, hdr[12, 4])
      w2_shift = IO::ByteFormat::LittleEndian.decode(Int32, hdr[16, 4])
      kb = IO::ByteFormat::LittleEndian.decode(Int32, hdr[20, 4])
      return false unless hh.in?(64..4096) && hid.in?(1..1024) && kb.in?(1..64)

      @@h = hh
      @@hid = hid
      @@wh_shift = wh_shift
      @@w2_shift = w2_shift
      @@acc_row = hh * 2
      @@king_buckets = kb

      w1_rows = FEATURES_PER_BUCKET * kb
      @@w1 = Pointer(Int16).malloc(w1_rows * hh)
      bytes_w1 = Bytes.new(w1_rows * hh * 2)
      h.read_fully(bytes_w1)
      LibMemory.memcpy(@@w1.not_nil!.as(Void*), bytes_w1.to_unsafe.as(Void*), w1_rows * hh * 2)

      @@wh = Pointer(Int16).malloc(hh * hid)
      bytes_wh = Bytes.new(hh * hid * 2)
      h.read_fully(bytes_wh)
      LibMemory.memcpy(@@wh.not_nil!.as(Void*), bytes_wh.to_unsafe.as(Void*), hh * hid * 2)

      @@bh = Pointer(Int16).malloc(hid)
      bytes_bh = Bytes.new(hid * 2)
      h.read_fully(bytes_bh)
      LibMemory.memcpy(@@bh.not_nil!.as(Void*), bytes_bh.to_unsafe.as(Void*), hid * 2)

      @@w2 = Pointer(Int16).malloc(2 * hid)
      bytes_w2 = Bytes.new(2 * hid * 2)
      h.read_fully(bytes_w2)
      LibMemory.memcpy(@@w2.not_nil!.as(Void*), bytes_w2.to_unsafe.as(Void*), 2 * hid * 2)

      @@enabled = true
      @@v4 = false
      true
    end

    # ENN4: magic, UInt32 width, feature-major Int16[768,width+1],
    # bias[width], phase output weights[2,width]. The final feature lane is
    # a learned linear PSQT path (scale 8); other lanes use scale 255.
    private def self.load_v4(data : String) : Bool
      width = IO::ByteFormat::LittleEndian.decode(Int32, data.to_slice[4, 4])
      return false unless width.in?(32..1024)
      expected = 8 + (768 * (width + 1) + 3 * width) * 2
      return false unless data.bytesize == expected
      weights = Pointer(Int16).malloc((expected - 8) // 2)
      io = IO::Memory.new(data.to_slice[8..])
      ((expected - 8) // 2).times do |i|
        weights[i] = io.read_bytes(Int16, IO::ByteFormat::LittleEndian)
      end
      @@h = width + 1
      @@acc_row = 2 * @@h
      @@w1 = weights
      @@bias = weights + 768 * @@h
      @@w2 = @@bias.not_nil! + width
      @@king_buckets = 1
      @@v4 = true
      @@enabled = true
      true
    end

    # Queenside (a-d) vs kingside (e-h) king bucket. Depends only on file, so
    # it is unaffected by the rank-mirroring used for POV1 squares. MUST
    # match tools/nnue_train.py's king_bucket exactly — this is the mapping
    # from square to bucket index, not just the bucket count (which is read
    # from the file header and doesn't need to match code on this side).
    @[AlwaysInline]
    def self.king_buckets : Int32
      @@king_buckets
    end

    def self.king_bucket(sq : Int) : Int32
      return 0 if @@king_buckets == 1
      (sq.to_i! & 7) < 4 ? 0 : 1
    end

    @[AlwaysInline]
    def feature_index(pc : Int, sq : Int, pov : Int, bucket : Int) : Int32
      pc = pc.to_i!
      sq = sq.to_i!
      color = pc // 6
      ptype = pc % 6
      if @@v4
        relative_color = color ^ pov.to_i!
        relative_square = pov.zero? ? sq : sq ^ 56
        return relative_color * 384 + ptype * 64 + relative_square
      end
      if pov.zero?
        rel = color.zero? ? sq : sq ^ 56
        slot = color.zero? ? 0 : 1
      else
        rel = color.zero? ? sq ^ 56 : sq
        slot = color.zero? ? 1 : 0
      end
      bucket.to_i! * FEATURES_PER_BUCKET + slot * 768 + ptype * 64 + rel
    end

    # dst = src adjusted by removals then additions. Indices are per
    # perspective: (w, b) pairs; counts select how many of the two slots apply.
    def self.apply_delta(dst : Pointer(Int32), src : Pointer(Int32),
                         rmw1 : Int32, rmb1 : Int32, rmw2 : Int32, rmb2 : Int32,
                         addw1 : Int32, addb1 : Int32, addw2 : Int32, addb2 : Int32,
                         rm_count : Int32, add_count : Int32) : Nil
      w1 = @@w1.not_nil!
      dst.copy_from(src, @@acc_row)
      hw = @@h
      acc_add(dst, w1, rmw1 * hw, rmb1 * hw, hw, -1) if rm_count >= 1
      acc_add(dst, w1, rmw2 * hw, rmb2 * hw, hw, -1) if rm_count == 2
      acc_add(dst, w1, addw1 * hw, addb1 * hw, hw, 1) if add_count >= 1
      acc_add(dst, w1, addw2 * hw, addb2 * hw, hw, 1) if add_count == 2
    end

    @[AlwaysInline]
    private def self.acc_add(dst : Pointer(Int32), w1 : Pointer(Int16),
                             base_w : Int32, base_b : Int32, hw : Int32, sign : Int32) : Nil
      # Two contiguous passes so LLVM can NEON-vectorize each accumulator.
      acc_axpy(dst, w1, base_w, hw, sign)
      acc_axpy(dst + hw, w1, base_b, hw, sign)
    end

    @[AlwaysInline]
    private def self.acc_axpy(dst : Pointer(Int32), w1 : Pointer(Int16),
                              base : Int32, hw : Int32, sign : Int32) : Nil
      src = w1 + base
      h = 0
      if sign > 0
        while h + 8 <= hw
          dst[h] += src[h].to_i32
          dst[h + 1] += src[h + 1].to_i32
          dst[h + 2] += src[h + 2].to_i32
          dst[h + 3] += src[h + 3].to_i32
          dst[h + 4] += src[h + 4].to_i32
          dst[h + 5] += src[h + 5].to_i32
          dst[h + 6] += src[h + 6].to_i32
          dst[h + 7] += src[h + 7].to_i32
          h += 8
        end
        while h < hw
          dst[h] += src[h].to_i32
          h += 1
        end
      else
        while h + 8 <= hw
          dst[h] -= src[h].to_i32
          dst[h + 1] -= src[h + 1].to_i32
          dst[h + 2] -= src[h + 2].to_i32
          dst[h + 3] -= src[h + 3].to_i32
          dst[h + 4] -= src[h + 4].to_i32
          dst[h + 5] -= src[h + 5].to_i32
          dst[h + 6] -= src[h + 6].to_i32
          dst[h + 7] -= src[h + 7].to_i32
          h += 8
        end
        while h < hw
          dst[h] -= src[h].to_i32
          h += 1
        end
      end
    end

    # Rebuild an accumulator row from scratch (used at root and after any
    # king move, since a moving king changes that perspective's bucket for
    # EVERY feature, not just its own).
    def self.refresh(row : Pointer(Int32), pos : Position) : Nil
      w1 = @@w1.not_nil!
      hw = @@h
      wbucket = king_bucket(pos.king_sq(WHITE))
      bbucket = king_bucket(pos.king_sq(BLACK))
      h = 0
      while h < @@acc_row
        row[h] = 0
        h += 1
      end
      sq = 0
      while sq < 64
        pc = pos.piece_at(sq)
        unless pc == NO_PIECE
          fi_w = feature_index(pc, sq, 0, wbucket)
          fi_b = feature_index(pc, sq, 1, bbucket)
          base_w = fi_w * hw
          base_b = fi_b * hw
          h = 0
          while h < hw
            row[h] += w1[base_w + h]
            row[hw + h] += w1[base_b + h]
            h += 1
          end
        end
        sq += 1
      end
    end

    # Evaluate from an accumulator row. Returns cp from the POV OF WHITE
    # scaled to centipawns (stm flip applied by caller like classical eval).
    def self.evaluate(row : Pointer(Int32), phase : Int32, stm_white : Bool) : Int32
      return evaluate_v4(row, phase, stm_white) if @@v4
      wh = @@wh.not_nil!
      bh = @@bh.not_nil!
      w2 = @@w2.not_nil!
      hw = @@h
      hid = @@hid

      # act (`a`, per accumulator unit): combine both perspectives, clamp
      # to +-512. Stack-allocated scratch since hid/hw are small (<=4096/1024).
      a = StaticArray(Int32, 4096).new(0)
      h = 0
      while h < hw
        v = row[h] + row[hw + h]
        v = -512 if v < -512
        v = 512 if v > 512
        a[h] = v
        h += 1
      end

      # hidden layer: clipped ReLU, per output unit j
      hidden = StaticArray(Int32, 1024).new(0)
      j = 0
      while j < hid
        acc = bh[j].to_i64
        h = 0
        while h < hw
          acc += a[h].to_i64 * wh[h * hid + j].to_i64
          h += 1
        end
        v = (acc >> @@wh_shift).to_i32!
        v = 0 if v < 0
        v = 512 if v > 512
        hidden[j] = v
        j += 1
      end

      out_mg = 0i64
      out_eg = 0i64
      j = 0
      while j < hid
        out_mg += hidden[j].to_i64 * w2[j].to_i64
        out_eg += hidden[j].to_i64 * w2[hid + j].to_i64
        j += 1
      end
      out_mg >>= @@w2_shift
      out_eg >>= @@w2_shift

      ph = phase.clamp(0, 24)
      blended = (out_mg * ph + out_eg * (24 - ph)) // 24
      # >> 9 (not 10): the engine's integer hidden-layer output (range
      # +-512) is never divided by 512 the way Python's float model is
      # before the final matmul, so `blended` here is exactly 512x Python's
      # `ev`. Shifting by 9 (=512) cancels that leftover factor.
      cp = (blended * 600) >> 9
      cp = stm_white ? cp : -cp
      cp.to_i32!
    end

    private def self.evaluate_v4(row : Pointer(Int32), phase : Int32, stm_white : Bool) : Int32
      width = @@h - 1
      bias = @@bias.not_nil!
      output = @@w2.not_nil!
      mg = 0i64
      eg = 0i64
      i = 0
      while i + 4 <= width
        w0 = (row[i] + bias[i]).clamp(0, 255)
        b0 = (row[@@h + i] + bias[i]).clamp(0, 255)
        d0 = (w0 - b0).to_i64
        mg += d0 * output[i]
        eg += d0 * output[width + i]
        w1 = (row[i + 1] + bias[i + 1]).clamp(0, 255)
        b1 = (row[@@h + i + 1] + bias[i + 1]).clamp(0, 255)
        d1 = (w1 - b1).to_i64
        mg += d1 * output[i + 1]
        eg += d1 * output[width + i + 1]
        w2 = (row[i + 2] + bias[i + 2]).clamp(0, 255)
        b2 = (row[@@h + i + 2] + bias[i + 2]).clamp(0, 255)
        d2 = (w2 - b2).to_i64
        mg += d2 * output[i + 2]
        eg += d2 * output[width + i + 2]
        w3 = (row[i + 3] + bias[i + 3]).clamp(0, 255)
        b3 = (row[@@h + i + 3] + bias[i + 3]).clamp(0, 255)
        d3 = (w3 - b3).to_i64
        mg += d3 * output[i + 3]
        eg += d3 * output[width + i + 3]
        i += 4
      end
      while i < width
        w = (row[i] + bias[i]).clamp(0, 255)
        b = (row[@@h + i] + bias[i]).clamp(0, 255)
        delta = (w - b).to_i64
        mg += delta * output[i]
        eg += delta * output[width + i]
        i += 1
      end
      ph = phase.clamp(0, 24)
      neural = (mg * ph + eg * (24 - ph)) // (24 * 255 * 64)
      linear = (row[width] - row[@@h + width]) // 16
      cp = (neural + linear).clamp(-28000, 28000).to_i32
      (stm_white ? cp : -cp) + 12
    end
  end
end
