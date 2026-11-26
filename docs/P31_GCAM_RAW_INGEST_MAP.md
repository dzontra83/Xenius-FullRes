# P31 — GCam LMC8.3 FullRes RAW ingress, traced from user's P24 APK

**Status (2026-11-15):** Verified ABI / Java call site and demonstrated first **offline 2×50 MP Bayer fusion**. **NOT a native GCam HDR+ integration, nor a new APK.** Stable P24 GCam / P30 FullRes apps are unmodified.

## Confirmed DEX call site (P24 classes.dex)

`com.google.googlex.gcam.hdrplus.HdrPlusInterface.addPayloadFrame` is declared **native** and accepts:
```java
static native boolean addPayloadFrame(
    long gcamPtr, int cameraId,
    long arg3, long arg4, long arg5, Runnable cb1,
    long arg7, Runnable cb2, long arg9, Runnable cb3);
```
(The meaning of individual long pointer arguments has **not yet** been fully traced: don't assume arg3 is a Java Image or directly memcpy RAW into it.)

Its **actual Java caller** is the obfuscated class `Lldh;`, method `l()Ljava/lang/Long;`:
- DEX method ID `44910`, code item offset `0x416534`, 344 instruction code units, 36 registers
- `invoke-static/range {v12 .. v28}, HdrPlusInterface.addPayloadFrame` at code-unit offset **292** (method ID `18796 = 0x496c`)
- Prior calls in the SAME method include:
  - `AndroidJniUtils.getAHardwareBufferPtr(HardwareBuffer)` at code-unit offset **177**
  - Construction of multiple `RawWriteView` objects at offsets **206, 244, 252**
  - `Gcam.a(Gcam)` native object pointer at **268**
  - `FrameMetadata.b(FrameMetadata)` native pointer at **276**
  - `SpatialGainMap.a(SpatialGainMap)` native pointer at **280**
  - `RawWriteView.d(RawWriteView)` native pointers at **284** and **288**
- This is a concrete **GCam RAW-ingest path**: HardwareBuffer → RawWriteView + per-frame metadata → addPayloadFrame.

## Native ABI address (P24 libgcastartup.so)

`Java_com_google_googlex_gcam_hdrplus_HdrPlusInterface_init` registers `addPayloadFrame` dynamically via `RegisterNatives`; the target native function in the P24 ELF is at **virtual address `0x10697a0`** (verified disassembly). On Android, add the library ASLR load base; the bare ELF virtual address is not a process pointer. Native wrapper forwards to internal function at `0x1070f30`. These addresses are **specific to the P24 binary**, not GCam releases in general.

This tells us precisely which path to instrument on a separate, diagnostic GCam build. A generic Java `Image` cannot be passed as one of the native `long` pointers; it requires valid GCam-owned RawWriteView / FrameMetadata / lifetime callbacks. **Do not call this function out of the proper GCam shot session.**

## FullRes frame source already working

P30 proved two distinct H85 and two distinct H35 frames: 8192×6144 `RAW_SENSOR` frames, 16-bit storage / 10-bit effective, CFA RGGB, white 1023, black ~=64, each with a distinct CaptureResult. Single DNG file size: 100,718,184 bytes (100,663,296 RAW image bytes plus TIFF header).

Offline proof: `scripts/p31_dual50_bayer_fusion.py` fuses **both H85 and H35** P30 B1/B2 pairs by pixel-wise rounded mean of original uint16 RGGB Bayer codes, producing two valid 8192×6144 DNGs with original TIFF tags and pixel layout. TIFF/DNG was reopened for both and H85 600×600 ROI confirmed exact arithmetic. H85 output 100,718,184 bytes (BlackLevel 64.01), H35 output 100,718,184 bytes (BlackLevel 63.90). **This is neither registered/aligned nor Google HDR+**. Potential motion ghosting; same-exposure fusion mainly reduces random noise, not exposure range.

## Exact next patch, in order

1. Instrument P24's existing `Lldh.l()` / `addPayloadFrame` in a **separate diagnostic GCam build**, logging input dimensions, format, pointers and shot IDs on a known-good **12.5 MP HDR+** burst. This must preserve ordinary GCam behavior.
2. Trace how `RawWriteView` gets constructed around `HardwareBuffer`, the corresponding `FrameMetadata`, `SpatialGainMap`, and three release callbacks. Avoid dangling GPU buffer references.
3. Add a FullRes Camera2 mode into the **same** GCam camera-owner/session code using P30 50 MP hardware protocol, with `VivoCameraManager key40` managed across open/close. No ZSL for FullRes; request 2 after shutter and pair each with matching CaptureResult timestamp.
4. Per-shot GCam native metadata: 8192×6144, RGGB, effective 10-bit, `BlackLevel~=64`, `WhiteLevel=1023`, per-frame ISO/exposure/noise/white balance. Do NOT change existing P24 14-bit D35/D85 DCG constants.
5. Only after a real `addPayloadFrame` path receives both frames, check `BeginPayloadFrames` → merge start/completion and actual output dimensions (ideally 8192×6144). Otherwise fail safely back to single 50MP DNG.

**Caveat:** GCam native merge support for 50MP geometry is **unverified**. Frame delivery and an offline average do not prove HDR+ compatibility. 2×200MP is ~765MiB RAW alone; first integrate 2×50MP.
