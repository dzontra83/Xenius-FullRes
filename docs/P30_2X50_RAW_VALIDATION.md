# P30 GCam Bridge — 2 × 50 MP RAW validation

Date: 2026-11-15. Source: user-supplied `Zip file(9).zip` containing 4 DNGs produced by Xenius P30 on Vivo X300 Ultra V2547A.

**Outcome: two independently captured 50MP DNGs exist for each camera. This is not yet GCam HDR+ merge.**

| Camera | RAW #1 | RAW #2 | Each DNG |
|---|---|---|---|
| ID 5 / H85 | `XENIUS_5_H50_B2_F1_1794750433801.dng` | `XENIUS_5_H50_B2_F2_1794750433987.dng` | 8192×6144, 100718184 bytes |
| ID 3 / H35 | `XENIUS_3_H50_B2_F1_1794750838868.dng` | `XENIUS_3_H50_B2_F2_1794750839042.dng` | 8192×6144, 100718184 bytes |

All TIFF/DNG IFD0s were parsed successfully, `Compression=1` (uncompressed Bayer `RAW16`), `BitsPerSample=16` storage, `WhiteLevel=1023`, `CFARepeatPatternDim=2×2`, `CFAPattern=RGGB`, orientation=6. `BlackLevel` is 64.01 for H85 and 63.90 for H35 (DNG TIFF rational). Both exposures were ISO 250 and 16,666,667 ns (1/60s). 50.33 million samples per frame.

## Independence / difference measurements

RAW strips are contiguous from byte offset 54888 (6144 rows × 16384 bytes each). An evenly spaced pixel sample from the central area (row/column step 16; N=182528 values) was compared for each camera's F1 and F2 after reading uncompressed uint16 pixels.

| Metric | H85 ID5 | H35 ID3 |
|---|---:|---:|
| Different raw samples | 89.52% | 94.63% |
| Mean absolute F1/F2 difference | 3.606 RAW codes | 6.907 RAW codes |
| Median absolute F1/F2 difference | 3 | 5 |
| 95th percentile absolute difference | 10 | 19 |
| Sample Pearson correlation | 0.9490 | 0.9868 |
| F1 sampled signal mean | 87.953 | 180.692 |
| F2 sampled signal mean | 87.941 | 180.779 |

**Interpretation:** data are distinct exposures with correlated scene signal, not duplicated RAW buffers. Small pixel differences are consistent with shot noise and/or small changes; validating accurate subpixel alignment requires further work.

## Limitations and next work

- No P30 `Downloads/XeniusFullResBridge` JSON metadata files were included in the ZIP, so this analysis cannot independently confirm per-frame `SENSOR_TIMESTAMP`, frame numbers, noise-profile arrays, dynamic black level or WB from those JSONs. DNGs contain general still EXIF metadata.
- This proves **2 × 50MP RAW burst + correct DNG representation**; **native GCam HDR+ was not invoked**. P30 itself logs `nativeHDRMerged=false`.
- Correct next step: inspect exact DEX→JNI `StartShotCapture / BeginPayloadFrames / RawImage` lifecycle in P24 LMC8.3 and design a frame adapter that supplies **each frame's RAW samples** plus matching dynamic `CaptureResult` (not only saved DNG) and shot-specific 10-bit `BlackLevel≈64 / WhiteLevel=1023` metadata.
- Start native ingestion with H85/H35 **2 × 50MP**, 200MP only after 50MP merge is genuinely confirmed. Maintain P24 and P29 untouched as known-good builds.
