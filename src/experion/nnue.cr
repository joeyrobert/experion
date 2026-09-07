# NNUE evaluation.
#
# Mirrors tools/nnue_train.py exactly:
#   features : 2 x 768 HalfKA (piece-color-square, both perspectives)
#   w1       : 1536 x H int16, feature-major (feature*H + h), scale *32
#   acc      : int32[H] per perspective, plain sum of w1 rows
#   act      : clamp(acc_w[h] + acc_b[h], -512, 512)                [a, per h]
#   hidden   : clamp((a . wh[:,j] + bh[j]) >> WH_SHIFT, 0, 512)     [per j]
#   out_c    : (hidden . w2[c]) >> W2_SHIFT
#   eval cp  : (blend(out_mg, out_eg) * 600) >> 9
#
# File format "ENN2": magic(4) H(4) HID(4) wh_shift(4) w2_shift(4) then
# w1(1536*H int16), wh(H*HID int16), bh(HID int16), w2(2*HID int16).
# wh_shift/w2_shift are chosen per-export from the ACTUAL trained weight
# magnitudes (see nnue_train.py's pick_shift) — a fixed shift picked in the
# abstract (the original OUT_SHIFT=20) silently overflowed int16 by ~70x for
# hours earlier this session before being caught by a direct sanity check
# against known positions. Never hardcode a shift here without that check.
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
      return false unless data.size > 20 && data[0, 4] == "ENN2"

      h = IO::Memory.new(data)
      hdr = Bytes.new(20)
      h.read_fully(hdr)
      hh = IO::ByteFormat::LittleEndian.decode(Int32, hdr[4, 4])
      hid = IO::ByteFormat::LittleEndian.decode(Int32, hdr[8, 4])
      wh_shift = IO::ByteFormat::LittleEndian.decode(Int32, hdr[12, 4])
      w2_shift = IO::ByteFormat::LittleEndian.decode(Int32, hdr[16, 4])
      return false unless hh.in?(64..4096) && hid.in?(1..1024)

      @@h = hh
      @@hid = hid
      @@wh_shift = wh_shift
      @@w2_shift = w2_shift
      @@acc_row = hh * 2

      @@w1 = Pointer(Int16).malloc(1536 * hh)
      bytes_w1 = Bytes.new(1536 * hh * 2)
      h.read_fully(bytes_w1)
      LibMemory.memcpy(@@w1.not_nil!.as(Void*), bytes_w1.to_unsafe.as(Void*), 1536 * hh * 2)

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
  end
end
