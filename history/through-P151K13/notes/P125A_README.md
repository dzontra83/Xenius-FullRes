# P125-A: Native BurstSpec frame requirements probe

Base: verified on-device P124-B FIX1, only `Ldvm.s` (begin-payload entry) changed.

Read-only native Java wrappers `BurstSpec.b()` and `FrameRequestVector.a()` reveal the number of frames Google requested for the current HDR+ burst. For up to two requests, log desired exposure (ms), desired analog gain and desired digital gain.

Expected line in `/sdcard/Download/RAW50_C_PROBE1.txt`:

`getBuffer:Gcam_BeginPayloadFrames:<count>:<frame0_exposure_ms>:<frame0_analog_gain>:<frame0_digital_gain>[:<frame1_exposure_ms>:<frame1_analog_gain>:<frame1_digital_gain>]`

This is NOT a merge! It does not alter Google HDR+ engine configuration, native shot state or payload routing; the original 12 MP payloads are still passed. Existing 2x96 MiB RAW copies and metadata are retained to the same boundary; image cleanup and raw-dng work remain unchanged.

Use the original NON-DCG FullRes XML. Keep P124-B FIX1 as fallback. Test one 50MP capture first, second only if the shutter finishes normally. Upload `RAW50_C_PROBE1.txt` and `RAW50_REQ.txt`; on crash/black preview supply full LADB logcat.

Only signature/DEX static checks are possible off-device.