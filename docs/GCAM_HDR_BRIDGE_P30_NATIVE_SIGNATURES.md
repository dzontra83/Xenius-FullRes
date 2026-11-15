# Xenius P30 — GCam HDR+ bridge: exact JNI contract and next integration point

Date: 2026-11-15. Scope: local Xenius P24 LMC8.3 `classes.dex` + `lib/arm64-v8a/libgcastartup.so`; and P29/P30 Camera2 source. **P30 is not an HDR+ implementation**.

## Proven capture behavior

- P29 on Vivo V2547A: user confirms two valid F85/F35 200MP DNG frames per `CameraCaptureSession.captureBurst`. Each image is matched by `Image.getTimestamp() == TotalCaptureResult.SENSOR_TIMESTAMP`. P27 confirmed 200MP DNG RGGB/BlackLevel64/WhiteLevel1023.
- P30 source extends P29 with two-frame **H85/H35 50MP** Camera2 `captureBurst` and per-frame JSON metadata sidecars; **P30 2x50 capture is untested on handset** until user reports.
- P24 separately handles the verified GCam ZSL HDR+ 12.5MP (10/10 and 15/15 merges observed). It is NOT modified.

## JNI method *signatures* extracted directly from P24 `classes.dex` method_ids + proto_ids

Original class: `Lcom/google/googlex/gcam/GcamModuleJNI;` (JNI symbols exported by `libgcastartup.so`).

```text
Gcam_StartShotCapture(long gcamPtr, Gcam obj, int camera, long shotParamsPtr,
    ShotParams shotParams, long callbacksPtr, ShotCallbacks callbacks, int mode,
    long postviewPtr, PostviewParams postview, long debugPtr, DebugParams debug) -> int shotId

Gcam_BeginPayloadFrames(long gcamPtr, Gcam obj, int shotId,
    long burstSpecPtr, BurstSpec burstSpec) -> void

Gcam_EndPayloadFrames(long gcamPtr, Gcam obj, int shotId,
    long clientMetadataPtr, ClientShotMetadata clientMetadata) -> boolean

Gcam_EndShotCapture(long gcamPtr, Gcam obj, int shotId) -> boolean

Gcam_OverrideFrameMetadata(long gcamPtr, Gcam obj, long keyPtr,
    FrameMetadataKey key, long frameMetadataPtr, FrameMetadata metadata) -> boolean

Gcam_BuildPayloadBurstSpec(long gcamPtr, Gcam obj, int cameraIndex,
    long rawReadViewPtr, RawReadView view, long frameMetaPtr, FrameMetadata metadata,
    long gainMapPtr, SpatialGainMap gainMap, long optionsPtr,
    BuildPayloadBurstSpecOptions options) -> long burstSpecPtr

new_RawImage__SWIG_1(int width, int height, int channels) -> long nativePtr
StaticMetadata_raw_bits_per_pixel_set(long staticPtr, StaticMetadata obj, int bits) -> void
StaticMetadata_white_level_set(long staticPtr, StaticMetadata obj, int white) -> void
StaticMetadata_frame_raw_max_width_set(long staticPtr, StaticMetadata obj, int width) -> void
StaticMetadata_frame_raw_max_height_set(long staticPtr, StaticMetadata obj, int height) -> void
FrameMetadata_black_levels_bayer_set(long metaPtr, FrameMetadata obj, float[] levels) -> void
```

Source of these **method prototypes** is P24 DEX metadata; source of **exported symbol names** is `readelf --dyn-syms --wide`. Wrapper symbols by themselves are **not** evidence of supporting 50/200MP direct ingestion.

## Native export RVA offsets in P24 libgcastartup.so (ELF virtual addresses)

- `Gcam_StartShotCapture`: `0x00e54e00`
- `Gcam_BeginPayloadFrames`: `0x00e5540c`
- `Gcam_EndPayloadFrames`: `0x00e554b0`
- `Gcam_EndShotCapture`: `0x00e554dc`
- `Gcam_OverrideFrameMetadata`: `0x00e54d60`
- `Gcam_BuildPayloadBurstSpec`: `0x00e54f6c`
- `StaticMetadata_raw_bits_per_pixel_set`: `0x00e517e0`
- `StaticMetadata_frame_raw_max_width_set`: `0x00e517b8`
- `StaticMetadata_frame_raw_max_height_set`: `0x00e517cc`
- `FrameMetadata_black_levels_bayer_set`: `0x00e4ee88`

**Crucial missing interface:** P24 SWIG `GcamModuleJNI` does **not** expose a simple `Gcam_AddRawFrame` JNI. There is no basis to call `BeginPayloadFrames` with a raw Android Image alone. Need identify the obfuscated GCam Camera2 ImageReader / HardwareBuffer frame submission path in DEX and map its callback into the native frame buffer manager, including shot ID and per-frame metadata keys.

## Next concrete code objective after P30 confirms H50 burst

1. In separate cloned P24 APK (never overwrite known working copy), instrument the Android Camera2 `ImageReader.OnImageAvailableListener` that forwards RAW images to GCam: record input image dimensions, surface name, format, shot ID and native queue callback for **one** 12.5MP frame. Do not change camera sessions yet.
2. Trace from that listener to `RawReadView` creation and frame metadata mapping; verify what frame ownership/lifetime the native queue expects.
3. Switch clone to P30-equivalent H50 Camera2 full-res session and **two 8192×6144 stills**, connecting to that identified frame ingest path with shot-specific Black64/White1023/10-bit semantics. Avoid 14-bit DCG metadata override in fullres mode.
4. Attempt native HDR+ merge of 2 frames with `ShotParams_nonzsl_frame_count_override_set(2)`, `ShotParams_zsl_set(false)`, and `ShotParams_save_merged_dng_set(true)`. These setters exist in P24 DEX; they do not prove 50MP merge works. Require logs verifying two *distinct* frames were merged.
5. Only after H50 succeeds attempt F200 with 2 frames, mindful of ~765MiB input memory before processing.

## Safe test expectations

P30 log should show:
```text
GCAM_BRIDGE_START
BURST_2_SUBMITTED ... mode=H50
BURST_2_FRAME_MATCHED ... index=1
BURST_2_FRAME_MATCHED ... index=2
GCAM_BRIDGE_METADATA_WRITTEN ... [twice]
GCAM_BRIDGE_FRAME_READY ... [twice]
BURST_2_FINAL ... saved=2/2 failures=0
GCAM_BRIDGE_PAIR_READY ... nativeHDRMerged=false
```

P30 does not prove HDR+ support. The next critical blocker is raw-frame injection into obfuscated GCam image-pump **without** introducing frame ownership errors, and is more challenging than merely setting native metadata values.
