# P175 (= P175F) — 200 MP → 50 MP binned mode on the Leica button + per-mode ZSL frame count (on P174B)

Run: `python3 build_p175.py XENIUS_P174B_UNSIGNED.apk XENIUS_P175F_UNSIGNED.apk` (`TBLOG=1` = merge.txt log build).
Needs `dexgen.py` and `libtbin.so` next to the script (plus the usual `tools/dex` and earlier builders).
Output: classes.dex `3bc9dd7c…04ff`, classes2.dex `7249d30e…7cea`, classes3.dex `129f6501…e88e` (new), lib/arm64-v8a/libtbin.so `c15715a2…7577` (new).

## Use
RES ON + Leica ON on 35 mm (ID3), 85 mm (ID5) and 200 mm teleconverter (ID9): the 50 MP stream becomes the 200 MP RAW
(16320×12256 / ×12288), each frame binned to 50 MP before HDR+. Leica OFF = normal 50 MP; RES OFF = 12 MP.
The Leica button no longer toggles shading mode (pref `setTemporalBinning`).

## How
- **Stream / keys** (from RawR `vivo_x300_ultra.json` F35/F85): same key40 gate; `vivo.control.ultra_highresolution=1`,
  `ai_highresolution=0`, `isUpscale=1` (+ ProRaw/echo/scenery/uiSwitch keys) in `Llel.h`, `Laue.a`, `Llei`; reader
  16320×(12256|12288), maxImages 6 in `Llel.c` / `Llfe.e` (camera id recorded by `Llel.e`); 200 MP flag = props `TemporalBinning`.
- **Binning** (`tbin.c`, freestanding NDK-less .so): RawR `BayerBin.h` sharp same-colour 2× kernel (phase preserving, local
  min/max clamp), then a same-colour linear stretch 8160×(6128|6144) → 8192×6144 (0.4 % / 0.26 %), no padding. ~0.75 s/frame.
- **Hook**: `Llet.<init>` (16320-wide RAW16) calls `TemporalBinning.a(image)` from classes3.dex by reflection (class name =
  an existing classes.dex string); it returns a one-plane `Lnns` list on a direct ByteBuffer, Llet reports 8192×6144;
  `Llet.f()` returns no HardwareBuffer for binned frames. Width checks in `Lleu` / `Ldvm.p` accept 16320.
- **Metadata**: 200 MP results carry COLOR_CORRECTION_GAINS = 0, black level 0, shading off → black photo. `Llei` stores
  the viewfinder's gains / CCM / neutral point; `Lohv.h` uses them and `Lohv.k` uses the static black level (64) in 200 MP mode.
- **Frames**: a burst of several 200 MP captures fails (2nd = REASON_ERROR). The burst sends 1 capture and queues the rest;
  each arriving 200 MP frame (`Lleu`) sends the next. Count = ZSL selector, 1..3 (GCam's minimum 2 lifted to 1 in 200 MP).
  Timing: 85 mm / ID9 ~1.2 s per frame, 35 mm ~4 s per frame (vivo HAL).
- **Per-mode ZSL count** (classes2): `LMC/lensvalue.SetLensValue` and `SetLensValueBack` append `FULL` (RES ON) or `leica`
  (RES ON + Leica ON) to `pref_zsl_frames_key` (+ lens suffix). 12 MP keeps the old key.

Tests (2026-11-20, merge.txt logs P175L..P175DL): 1/2/3 frames on 35/85 mm and ID9, correct colour, no edge streak.
