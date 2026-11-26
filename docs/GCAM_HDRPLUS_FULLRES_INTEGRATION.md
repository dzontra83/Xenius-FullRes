# Xenius — GCam HDR+ / Vivo FullRes integration investigation (2026-11-15)

Status: **architecture + evidence verified, GCam FullRes HDR+ NOT IMPLEMENTED**. Do not advertise P27 200MP RAW capture as HDR+.

## Verified local evidence

- Xenius P24 LMC 8.3 12.5MP HDR+ already merges bursts successfully: captured logs contain `MERGED_RAW` with **10/10** and **15/15**, `aborted=false`.
- P27 Camera2 FullRes app makes DNG from `H35/H85` at 8192×6144 and `F35/F85` at 16320×12256 and 16320×12288. Valid 200MP DNGs have TIFF `BitsPerSample=16` (storage), `BlackLevel=64`, `WhiteLevel=1023` (10-bit meaningful samples), CFA=RGGB, Orientation=6. These confirm frame delivery but not the true optical 200MP resolving power.
- P27 has **single-shot fullres capture only** on the user's V2547A. No fullres burst has yet been tested there.
- The source of P27 is `XENIUS_P27_F200_BLACKLEVEL64_SOURCE.zip`, and P24 remains an independent already-installed APK.

## Relevant existing GCam native interfaces (found in P24 libgcastartup.so dynamic JNI symbols)

- `Gcam_StartShotCapture`, `Gcam_BeginPayloadFrames`, `Gcam_EndPayloadFrames`, `Gcam_EndShotCapture`
- `Gcam_OverrideFrameMetadata`, `Gcam_BuildPayloadBurstSpec`
- `StaticMetadata_raw_bits_per_pixel_{get,set}`, `StaticMetadata_white_level_{get,set}`
- `StaticMetadata_frame_raw_max_width_{get,set}`, `StaticMetadata_frame_raw_max_height_{get,set}`
- `FrameMetadata_black_levels_bayer_{get,set}`, `FrameMetadata_dng_noise_model_bayer_{get,set}`
- `new_RawImage__SWIG_0/1`, `RawReadView`, `RawWriteView`

Existence of a JNI setter **does not prove that native merger/GPU pipelines support 200MP**. Trace invocation and accepted buffer layout before patching hardcoded limits. Never change P24 D35/D85 DCG levels globally.

## Required new FullRes mode within GCam

1. **Before camera open:** acquire VivoCameraManager gate key40=1; preserve and restore previous value, including errors / camera close. The mode must be separate from P24 regular DCG because the 10-bit fullres still pipeline and 14-bit forced-DCG preview path may be incompatible.
2. **Session outputs (P27-proven):** RAW_SENSOR preview 4080×3064 (ID3) or 4080×3072 (ID5); RAW_SENSOR still 8192×6144 (H50), 16320×12256 (F35), or 16320×12288 (F85); small YUV_420_888 companion. FullRes reader uses `HardwareBuffer.USAGE_GPU_DATA_BUFFER`. Gate held until device close.
3. **Session + Request vendor configuration:** mirror P27/RawR public profile for `ultra_highresolution=1`, `is_ProRaw_on=2`, `echo.mode=2`, `scenery.subfunction=5`, `session.uiSwitch_state=2` and still fields `onlyDng=1`, `isUpscale=1`, `com.vivo.current_ui_module=74`, and vendor int64 request/frame/global IDs; for H50 use H50 selection, not F200.
4. **F200 decision:** use YUV-only preparatory repeating request carrying `current_ui_module=74`, low ISO, wait for result, stopRepeating, then send still requests to BOTH RAW outputs. Do not place UI module 74 on normal RAW viewfinder requests. No regular ZSL burst can contain F200 RAW because only still path is fullres.
5. **Frame/metadata adapter:** match RAW `Image` with `TotalCaptureResult` by `SENSOR_TIMESTAMP` (P27 last-result singleton is insufficient for bursts). Correct row stride / GPU buffer ownership, Bayer phase and active crop. Feed original 16-bit-stored RAW samples with **10-bit raw signal semantics**, `BlackLevel=64`, `WhiteLevel=1023`, RGGB, per-frame exposure ISO/gain, WB, noise model, OIS/time and lens geometry. Avoid the P27 workaround of fixing DNG metadata after saving: HDR+ needs corrected metadata **before merge**.
6. **Native GCam processing:** integrate the fullres-frame source with the SWIG `RawImage`/frame callback path and burst lifecycle. Increase shot-specific `StaticMetadata.frame_raw_max_width/height` and set `raw_bits_per_pixel` and white level for fullres only. Check GPU texture dimensions, allocation failures, alignment tile dimensions, ISP metadata conversion, frame ownership and output JPEG/DNG target dimensions. Determine whether existing native merger can accept 50MP/200MP; do not assume.
7. **Recovery:** if GCam merge rejects fullres geometry or buffer format, save the valid single-frame fullres DNG rather than corrupt output, and restore normal session/gate.

## Practical staged experiments

- **A — V2547A HAL two-frame proof:** extend P27 to capture TWO F85 200MP RAW frames as one properly correlated burst. Log frame timestamps, actual effective resolution, ISO/exposure, decision completion, per-frame black levels, and whether two 200MP buffers are received. Do not process or call this HDR+. Preserve single shot. After that test F35.
- **B — 50MP bridge:** add a GCam FullRes-specific session, capture TWO 50MP frames, deliver raw samples + corrected per-frame metadata into GCam raw ingest, and record `StartShotCapture`, `BeginPayloadFrames`, and merge callbacks. 50MP is a safer compatibility test.
- **C — 200MP bridge:** start with 2 frames (not 10/15); if merger works, try 3; separately measure memory, latency, output 200MP dimensions and highlight/denoise behavior.

### Memory baseline

Packed in RAW16 storage: 50MP still = 96 MiB/frame; F35 = 381.5 MiB/frame; F85 = 382.5 MiB/frame. F85 **2 frames ~765 MiB; 3 ~1.12 GiB; 6 ~2.24 GiB**, **before** CPU copies, alignment buffers, demosaic, output and GPU textures. A 12MP-tuned ZSL/GCam pipeline should not be expected to hold 10/15 F200 frames.

RawR docs report limited multiframe successes on **global V2562** (e.g. 6/8 queued; 16 sequential); 16 queued crashed camera provider. This is not a result for user's **V2547A**.

## Specific hazards to instrument

- `VIVO_GATE_STATE` before/after open + close, `FULLRES_SESSION_CONFIGURED` and output dimensions
- `F200_DECISION_DONE` + timing, `seamlessMode` where readable
- Per `RAW_FRAME_RECEIVED`: timestamp, width, height, rowStride, raw channel pattern, min/max, RAW mode
- Per `RESULT_MATCH`: timestamp delta, sensor ISO, exposure_ns, black level, white level, noise profile
- `GCAM_RAW_INGEST` and `GCAM_MERGE_START/COMPLETE/FAIL` with shot ID, 2 frames, memory and elapsed time
- Detect binned-in-corner fallback despite fullsize allocated buffer

## Sources

- RawR docs: https://github.com/adityawarmanfw/rawr/blob/main/docs/vivo-fullres.md
- Android RAW_SENSOR: https://developer.android.com/reference/android/graphics/ImageFormat
- Android CaptureResult dynamic black level: https://developer.android.com/reference/android/hardware/camera2/CaptureResult
- Google HDR+ algorithm: https://research.google/pubs/burst-photography-for-high-dynamic-range-and-low-light-imaging-on-mobile-cameras/
