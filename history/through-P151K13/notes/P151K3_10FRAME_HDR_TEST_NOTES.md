# Xenius P151K3 — 10-frame native FullRes HDR+ test (2026-11-18)

## Purpose
Experiment with RAW50/HDR+ 6–10 frames, starting from the user-confirmed stable **P151K2 FORCE_KEY40_OFF_ONCLOSED**. **Do not overwrite P151K2 stable**.

## Reference
Older P150D/F150D proved native 5/5-frame merge using `acquireNextImage()`; P151C added per-lens 2/3/5 selection with dynamic Camera2 RAW requests and HDR+ native count. P151K2 adds reliable forced key40=0 after main CameraDevice.onClosed.

## Binary patch
Only `classes.dex`, method `Llei.onCaptureCompleted` (DEX method #45060), code units **79–92**. The method resolves lens-specific `pref_zsl_frames_key` via `LMC/lensvalue.SetLensValue`, reads the ZSL frames value (default string "5"), and uses it for a CameraCaptureSession.capture loop while placing the selected integer in `System.getProperties()["pref_hdrnet_key"]` for the native FullRes HDR+ count.

Old clamp: minimum 2, maximum 5, invalid/nonpositive -> 5.
New clamp: minimum 2, maximum 10, invalid/nonpositive -> 2. When no preference exists default remains 5.

Same 14 Dalvik code units; no method-size increase, branch relocation, try handler changes, or changes to `ImageReader` maxImages (=5). The acquired camera image is released per callback in the existing FullRes implementation. `maxImages` is therefore NOT the number of frames in one burst, although >5-frame buffer backpressure remains a possible on-device failure.

No changes to `classes2.dex` (key40 helper), other code, native `.so`, resources, DNG cleanup, package, camera settings, or native metadata.

## Verification
- Exact 14 code units inspected before patch; new code instruction boundaries and all branch targets verified.
- Whole DEX checksums updated; only 48 bytes differ vs P151K2 `classes.dex` including checksum bytes.
- The whole archive differs from K2 only in `classes.dex`.
- ZIP CRC test and uncompressed resources.arsc 4-byte alignment passed.
- V2 signing with the exact same previously generated Xenius P151K2 experimental certificate. Independent RSA-SHA256 signature and content digest verified. Android's apksigner not available; device installation still to be tested.

## Test sequence
1. Keep original working P151K2 APK saved. Use key40 helper READ=0 before launching (if camera is idle).
2. Install the P151K3 signed APK if and only if current P151K2 signature matches; otherwise sign the unsigned build in MT Manager using the previous certificate.
3. Set **ZSL Frames** for relevant lens to 3 first. Capture two 50MP images. Confirm original/merged count=3/3.
4. Increase to 6 (if menu supports), 9, then 10. For a menu value above 10 (such as 12 or 25), the experimental code intentionally caps it at 10. If 10 is not directly selectable, menu 12 or 25 can test the 10 cap.
5. For each selected value, wait for the image to save and check native 8192×6144 frame results. Avoid rapid repeated 10-frame captures initially to limit memory pressure.
6. Exit Xenius, use the independent key40 utility READ; must be 0. Verify stock Vivo camera. Reopen Xenius and repeat one shot.
7. On trouble, capture log immediately:
   `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K3_10FRAME_TEST.txt`

## Expected log
Look for `ShotLogData_original_payload_frame_count_get`, `ShotLogData_merged_frame_count_get` equaling the selected count, `ShotLogData_aborted_get=false`, and `VIVO_GATE: 0` after `onClosed`. `VIVO_GATE` messages are requested setValue operations; use the independent READ utility for real gate state. Native Google HDR+ acceptance of 10 frames is not established by offline verification.

## Safety
P151K3 is **experimental**, not yet a replacement for P151K2. At 50MP ×10 the RAW/HDR+ pipeline is memory-intensive. A stall/abort at 6–10 may require modifying buffer capacity or native shot limits, but do not change these unless log evidence warrants it.