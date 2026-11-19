# P151K5 — 25 ms paced full-resolution RAW acquisition experiment

## Goal
Find out whether the intermittent 6–8-frame full-resolution HDR+ failure is related to submission pressure and timing. The user observed that some 7/8-frame telephoto HDR+ merges succeed, so there is no demonstrated universal five-frame native limit. This build borrows RawR's *separation and pacing* principle only. It is **not** a complete RawR-style frame acknowledgement/synchronization barrier, and does not replace the native GCam merger.

## Based on
P151K4 experimental (2–10 requested RAW frames and ImageReader maxImages=12), which itself preserves P151K2's user-confirmed stable automatic key40 OFF at CameraDevice.onClosed and temporary DNG cleanup. P151K2 is unchanged and must remain stable fallback.

## Patch detail
`classes.dex`, method `Llei.onCaptureCompleted` (#45060), code unit 115 branch rerouted from the tight loop to existing NOP space at code units 118–128. After each nonfinal `CameraCaptureSession.capture()` request, before submitting the next, the code now performs `SystemClock.sleep(25L)` and then loops back to the original request. The final request returns immediately without sleeping. This adds 125 ms of delay for 6 frames and 225 ms for 10 frames; actual exposure/capture latency is additional.

To preserve the callback Handler in `v3`, the injected code saves it temporarily to `v4`, uses `v2/v3` as a long argument for `SystemClock.sleep`, restores `v3`, and branches to the existing capture instruction. The loop counter `v0` remains intact. The method's code size, try blocks, original capture instruction and the payload/native HDR+ paths are unchanged. All other APK entries, including classes2.dex/key40, are byte-for-byte identical to K4.

**Caution:** The callback appears to use `Handler(Looper.getMainLooper())`. The added pacing can briefly stall the viewfinder/UI for up to ~225 ms in a ten-frame burst. This is a diagnostic tradeoff. It should not be considered a production fix unless on-device tests demonstrate consistent improvement and acceptable responsiveness.

## Suggested test
1. Keep the P151K2 signed APK backed up. Confirm key40 starts at 0 (standalone READ tool). Install P151K5 signed if its certificate matches your current install; otherwise sign the unsigned APK using MT Manager.
2. In Xenius test one 3-frame and one 5-frame image (baseline), then **three separate 6-frame shots**, allowing each to finish or fail; if six frames becomes reliable, try seven and eight. Only try 9/10 if 6/7/8 are repeatedly reliable.
3. Do not shoot while another processing job is running. If the app hangs, gets hot or doesn't save an image, stop repeated testing.
4. Check key40 has returned to 0 after exiting and that stock camera opens.
5. Generate a **fresh** log: `logcat -c` before opening Xenius for the test, then `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K5_PACED25_TEST.txt` immediately after testing. Also share the updated `RAW50_C_PROBE1.txt`. Tell us which shot/count succeeded and which failed.

Success criterion: actual native 6/6 (or 8/8) HDR+ merged output, repeatedly. Arrival of six Camera2 RAW frames alone is insufficient. There is no hardware test result yet.

## Offline verification
DEX instruction alignment, branch targets, try-block boundaries, minimum code differences, ZIP integrity, and unchanged all files except classes.dex passed. APK Signature Scheme v2 RSA-SHA256 signer and content digest independently verified with the same development signing key as previous K2/K3/K4 signed experiments. Standard `apksigner` is unavailable here. Installation and behavior require testing on the Vivo.