# Xenius P151K11 — restore global key40 acquisition, preserve ID9 TC

## Confirmed from P151K10 log
- 2026-11-19 01:10:58.524 `RESOLUTION_SWITCH: onResume`, but P151K10 deliberately removed `LMC/c2a.getC2apiPref(null)` from onResume.
- 01:11:01.189 shot ID 0 (valid) enters Gcam_BeginPayloadFrames; four raw frames are passed to the pipeline.
- 01:11:01.194 `Image is already closed` exceptions in `dvm.p`; some similar errors were nonfatal in K2, so not sufficient by themselves to identify the root cause.
- 01:11:01.199 libgcam reports `Expected 33.3 ms gap; actual gap was 0.0 ms`; `No base frame candidates found`, aborts HDR+ shot. Other errors follow including a secondary `ClassCastException lei cannot be cast to android.net.Uri` in dvm.n, and no saved photo.
- 01:11:03.308 `VIVO_GATE:0` on shutdown; this is not proof of the gate value while running.

## Corrected key40 semantics
- In K2 classes2 `LMC/c2a.getC2apiPref(Lleo)`, **null argument = acquire key40 (setValue(40,1) when needed)**; nonnull wrapper with null builder = release key40. P151K10 incorrectly interpreted null as release and removed the principal onResume acquisition, a regression.
- K11 rebuilt from P151K9, NOT from flawed K10. onResume null-acquisition restored exactly as in user-confirmed stable K2/K9.
- Added only a new global camera-open acquisition attempt in Lksn.onOpened after original nonnull getClass check, before existing callback logic. Calls `LMC/c2a.getC2apiPref(null)` once for every camera onOpened. The K2 helper reads current key40, does not needlessly write if already 1. Then logs `RAW50_REPEAT: CameraDevice#onOpened`.
- Existing K9 ID9 TC `extLensInfo=[1,200,2]` session + active preview + FullRes still remains unchanged. Global 50 MP engine, 2–5 frames, native libs and key40 onClosed OFF are untouched.

## Verification and limitations
- APK built, DEX parsed, control-flow branch targets checked, all other original methods untouched, ZIP checked, resources.arsc alignment checked. Same certificate as K2/K9. v2 RSA-SHA256 certificate/digest independently verified.
- No Android runtime or actual photograph test available. This is a targeted candidate fix, NOT validated stable.
- **Key40 may not be the only root cause**; HDR+ reported broken raw frame timing and closed images in K10. If K11 shows key40=1 but capture still fails, investigate payload timestamp and image lifecycle instead of further gate changes.

## Test
1. Force-stop application. Start on Camera ID5 with 3 RAW HDR+ frames.
2. Check independently key40 READ while active (should be 1). Take photograph and confirm file saved.
3. Select Additional Lenses Camera 4 (ID9), attached physical teleconverter, confirm ID9-only shaky preview and try 3-frame photo.
4. Exit Xenius. Independently READ key40; should be 0. Test stock camera.
5. If failure: collect `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K11_LOG.txt`, including `RAW50_REPEAT: CameraDevice#onOpened`, `VIVO_GATE:1/0`, Gcam error and libgcam timestamps.

Stable fallback: P151K2.