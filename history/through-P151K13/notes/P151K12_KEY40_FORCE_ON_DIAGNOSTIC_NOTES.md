# Xenius P151K12 — Force key40 acquisition / diagnostic

19 November 2026. Experimental build from P151K11 (not a confirmed repair).

## User observation
P151K9 achieved distinctive ID9 physical teleconverter preview movement, but no lens could save photographs and external key40 read remained 0. P151K10 removed the acquisition call by mistake; P151K11 restored it and added another call on camera onOpened; user still measured key40 0 in P151K11. No P151K11 log has been supplied to establish the actual reason.

## Code investigation
`classes2.dex` method `LMC/c2a.getC2apiPref(Lleo;)`, DEX index 646:
- null argument branches at CU0->338, requests the **ON** path (v5=1).
- nonnull wrapper with null builder takes the **OFF** path (used by `Lksn.onClosed`). K2 unconditional OFF policy remains.
- ON previously ran `getInfo(40)` and at CU408 `if-nez v4, CU485`, silently skipping `setValue(40,1)` when the value read by this helper was nonzero.
- P151K12 changes **only CU408-409** to two NOPs, so each attempted ON acquisition continues into `setValue(40,1)` regardless of the read's value.
- The OFF path, key40 0 write and the 200 ms sleep in original helper are untouched. The K11 `Lksn.onOpened` global ON attempt and K2 `CameraActivity.onResume` ON attempt remain.
- `classes.dex` is byte-for-byte identical to K11, retaining the P151K9 ID9 TC preview/vendor key, camera-open call, unchanged 2–5-frame HDR+, and all native libraries.

## What this test will establish
- `I/VIVO_GATE: 1` in logs means the helper has **attempted** `setValue(40,1)`. It is not independent proof the hardware value actually changed. Read key40 externally while the app is open.
- `I/VIVO_GATE: 1` followed by `I/VIVO_GATE: 0` before the user closes Xenius suggests a camera onClosed release race.
- No `VIVO_GATE: 1` after both CameraDevice.onOpened and onResume suggests an exception or another early exit; inspect `E/VIVO_GATE` and log timestamps.
- If key40 independently reads 1 but photographs still fail, inspect native GCam/RAW50 timestamp/merge, not the gate.

## Test
1. Force stop previous Xenius; verify external key40 read 0 before launch.
2. Install P151K12, open ID5, *while still in the viewfinder* independently read key40. Try a 3-frame photo and inspect if saved.
3. Switch to Additional Lenses Camera 4 (ID9), attach TC, check distinctive preview and attempt 3-frame 50 MP capture.
4. Close app, read key40; should go back to 0. Test stock camera.
5. If any failure, without clearing logs or opening other cameras, use `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K12_KEY40_LOG.txt`.

## Verification
Build script `build_p151k12_force_key40_acquire.py` checked method identity, only two changed Dalvik CU, valid instruction boundaries and branches, DEX checksum/SHA1, ZIP integrity, all unchanged entries and resources. `sign_xenius_p151k12_v2.py` used existing Xenius development certificate, and independently parsed/verified RSA-SHA256 Android APK Signature Scheme v2 and full APK digest. Not installed or tested on the actual Vivo; standard `apksigner` unavailable in this environment.

Stable fallback is P151K2, which remains unchanged.