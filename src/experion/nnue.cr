# NNUE evaluation.
#
# Mirrors tools/nnue_train.py exactly:
#   features : 2 x 768 HalfKA (piece-color-square, both perspectives)
#   w1       : 1536 x H int16, feature-major (feature*H + h), Q1 = 1024
#   acc      : int16[H] per perspective, plain sum of w1 rows
#   act      : clamp(acc_w[h] + acc_b[h], 0, Q1)
#   out_c    : sum_h act[h] * w2[c][h] >> 12     (int64 accumulator)
#   eval cp  : (blend(out_mg, out_eg) * 600) >> 9
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

    Q1     = 1024
    # must match tools/nnue_train.py's OUT_SHIFT exactly. 20 let trained w2
    # (commonly magnitude ~2-3) overflow int16 by up to ~70x at export time,
    # silently corrupting the output layer — every net exported with the old
    # value evaluates as near-degenerate regardless of training quality.
    OUT_SHIFT = 12

    @@w1 : Pointer(Int16)? = nil
    @@w2 : Pointer(Int16)? = nil
    @@enabled = false
    @@disabled_by_option = false
    @@blend = 100
    @@h : Int32 = 256        # hidden width from the loaded file
    @@acc_row : Int32 = 512  # 2 * h

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
      return false unless data.size > 8 && data[0, 4] == "ENN1"

      h = IO::Memory.new(data)
      hdr = Bytes.new(8)
      h.read_fully(hdr)
      hh = IO::ByteFormat::LittleEndian.decode(Int32, hdr[4, 4])
      return false unless hh.in?(64..4096)

      @@h = hh
      @@acc_row = hh * 2
      @@w1 = Pointer(Int16).malloc(1536 * hh)
      @@w2 = Pointer(Int16).malloc(2 * hh)
      bytes_w1 = Bytes.new(1536 * hh * 2)
      h.read_fully(bytes_w1)
      LibMemory.memcpy(@@w1.not_nil!.as(Void*), bytes_w1.to_unsafe.as(Void*), 1536 * hh * 2)
      bytes_w2 = Bytes.new(2 * hh * 2)
      h.read_fully(bytes_w2)
      LibMemory.memcpy(@@w2.not_nil!.as(Void*), bytes_w2.to_unsafe.as(Void*), 2 * hh * 2)

      @@enabled = true
      true
    end

    @[AlwaysInline]
    def feature_index(pc : Int, sq : Int, pov : Int) : Int32
      pc = pc.to_i!
      sq = sq.to_i!
      color = pc // 6
      ptype = pc % 6
      if pov.zero?
        rel = color.zero? ? sq : sq ^ 56
        slot = color.zero? ? 0 : 1
      else
        rel = color.zero? ? sq ^ 56 : sq
        slot = color.zero? ? 1 : 0
      end
      slot * 768 + ptype * 64 + rel
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
      if rm_count >= 1
        base_w = rmw1 * hw
        base_b = rmb1 * hw
        h = 0
        while h < hw
          dst[h] -= w1[base_w + h]
          dst[hw + h] -= w1[base_b + h]
          h += 1
        end
      end
      if rm_count == 2
        base_w = rmw2 * hw
        base_b = rmb2 * hw
        h = 0
        while h < hw
          dst[h] -= w1[base_w + h]
          dst[hw + h] -= w1[base_b + h]
          h += 1
        end
      end
      if add_count >= 1
        base_w = addw1 * hw
        base_b = addb1 * hw
        h = 0
        while h < hw
          dst[h] += w1[base_w + h]
          dst[hw + h] += w1[base_b + h]
          h += 1
        end
      end
      if add_count == 2
        base_w = addw2 * hw
        base_b = addb2 * hw
        h = 0
        while h < hw
          dst[h] += w1[base_w + h]
          dst[hw + h] += w1[base_b + h]
          h += 1
        end
      end
    end

    # Rebuild an accumulator row from scratch (used at root).
    def self.refresh(row : Pointer(Int32), pos : Position) : Nil
      w1 = @@w1.not_nil!
      hw = @@h
      h = 0
      while h < @@acc_row
        row[h] = 0
        h += 1
      end
      sq = 0
      while sq < 64
        pc = pos.piece_at(sq)
        unless pc == NO_PIECE
          fi_w = feature_index(pc, sq, 0)
          fi_b = feature_index(pc, sq, 1)
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
      w2 = @@w2.not_nil!
      hw = @@h
      out_mg = 0i64
      out_eg = 0i64
      h = 0
      while h < hw
        a = row[h] + row[hw + h]
        a = -512 if a < -512
        a = 512 if a > 512
        out_mg += a.to_i64 * w2[h].to_i64
        out_eg += a.to_i64 * w2[hw + h].to_i64
        h += 1
      end
      out_mg >>= OUT_SHIFT
      out_eg >>= OUT_SHIFT
      ph = phase.clamp(0, 24)
      blended = (out_mg * ph + out_eg * (24 - ph)) // 24
      # >> 9 (not 10): the engine's integer activation (`a`, range +-512)
      # is never divided by 512 the way Python's float `act` is before the
      # matmul, so `blended` here is exactly 512x Python's `ev`. Shifting by
      # 9 (=512) cancels that leftover factor; the training script's ev*600
      # is the actual target scale.
      cp = (blended * 600) >> 9
      cp = stm_white ? cp : -cp
      cp.to_i32!
    end
  end
end
