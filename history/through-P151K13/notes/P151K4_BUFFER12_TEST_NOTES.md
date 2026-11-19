# P151K4 — FullRes ImageReader capacity experiment

## Why
User reports P151K3 completed HDR+ up to 5 frames but did not process at values >5. In P151K3 the 50MP capture-request count was extended to 2–10 while both RAW50 ImageReader instances retained maxImages=5. The user-provided P151K3_10FRAME_TEST.txt shows Xenius camera activity and `processing` notifications, but no app-side `RAW50_REQ` or HDR+ native frame count diagnostics for the failures; thus queue congestion is a plausible hypothesis, not a proved cause.

## Changes from P151K3
- classes.dex / Llel.c / ImageReader.newInstance: `const/16 v12, 5` → `const/16 v12, 12`, CU77.
- classes.dex / Llfe.e / ImageReader.newInstance: `const/16 v8, 5` → `const/16 v8, 12`, CU51.
- 2–10 selected RAW requests and native handoff remain unchanged. The two 50MP capture paths now have maxImages=12 for the duration of the session.
- P151K2's forced Key40 OFF on real CameraDevice.onClosed, DNG cleanup, Android resources, native libraries, and all other APK files unchanged.
- This does not remove any hypothetical cap in native GCam and may use significantly more RAW buffers/RAM.

## Verify on-device
1. Preserve user-confirmed stable P151K2. Install P151K4 signed APK if certificate matches; otherwise use MT Manager to sign unsigned version consistently.
2. With key40 READ=0, start Xenius, choose 3 frames and capture one 50MP shot (control).
3. Choose 5, then 6. Only continue to 7, 8, 9, 10 one at a time if each prior shot completes successfully. Allow processing to finish before changing frame count or taking another photo. Stop if freezing/heat/memory symptoms.
4. Success requires native log `ShotLogData_original_payload_frame_count_get = 6`, `ShotLogData_merged_frame_count_get = 6`, and `aborted=false` (similarly 10/10). Saving a JPEG by itself is not evidence of 10 HDR frames.
5. Close Xenius, verify key40=0 and the stock Vivo camera works.
6. For failure capture immediately with LADB: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K4_BUFFER12_TEST.txt`; avoid capturing after extensive unrelated app use, because main ring buffer overwrites earlier lines.

## Offline checks
Only two Dalvik const/16 literal words changed, plus the header checksum and SHA1 fields. Instruction boundaries, branch targets, ZIP archive, unchanged other file content, resources.arsc alignment and APK signing v2 RSA-SHA256 verified. Standard Android `apksigner` executable not available in environment, so installability still needs phone confirmation.

## Status
**EXPERIMENTAL**, unverified on hardware. Do not promote to stable until ≥6 native frames actually merge AND key40 correctly restores on repeated opens. P151K2 is untouched stable fallback.