# Xenius P151K10 — experimental key40 reacquire timing fix

## Confirmed user observations
- P151K9 shows the distinctive active teleconverter shaky viewfinder **only on Camera 4 / ID9**.
- P151K9 cannot take photographs **on any lens**; external read shows Vivo key40 stays `0`.
- Hence the ID9-only teleconverter preview activation should be preserved, and key40 global lifecycle addressed separately.

## Root cause hypothesis (not yet proven without a P151K9 live log)
- In P151K9, `CameraActivity.onResume` logs `RESOLUTION_SWITCH:onResume`, then passes `null` to `LMC/c2a.getC2apiPref(Lleo)`. The null path is the **release/OFF** path; the stable P151K2 helper now **unconditionally** sets key40 `0` on this path.
- Other code invokes the helper with a non-null active CaptureRequest.Builder wrapper to set key40 `1` when required. A preview / session constructed before activity resume may therefore turn the gate ON and then have onResume immediately turn it OFF.
- The previous P151K7 log had `LMC_TC_SESSION` session configuration at 00:41:09.710, ahead of `RESOLUTION_SWITCH:onResume` at 00:41:09.724. This proves ordering may be nonintuitive, but does **not** by itself prove key40 was ever set ON in that trace.

## Single experimental patch from P151K9
- In `classes.dex`, `CameraActivity.onResume`, DEX method ID 15529, CU 8–10: remove the redundant `invoke-static {v0}, LMC/c2a.getC2apiPref`, where CU7 has `const/4 v0,0`, by replacing the three instruction code units with NOPs. The remaining Activity onResume code is untouched.
- `CameraActivity.onCreate` initial null-release retained. `Lksn.onClosed` cleanup/release retained. The non-null `Llel.h` request-builder invocation retained.
- All of P151K9's ID9-only `vivo.control.extLensInfo=[1,200,2]` session + repeating/request + FullRes capture changes unchanged. `classes2.dex` and the stable 5-frame HDR+ paths unchanged.
- Changed exactly 6 bytes in `classes.dex` instructions; recomputed DEX SHA1/Adler32 checksums; assembled APK with unchanged other entries.

## Verification and limits
- DEX instruction boundary and branch-target checks passed. All original methods and resources except 3 CU onResume unchanged. APK ZIP CRC, resource alignment and independently parsed v2 signature/digest verified. Same experimental development certificate as P151K2/9.
- Android phone runtime and key40 readback **not tested**. The race is a plausible cause, not a proven diagnosis; if key40 remains `0`, investigate whether the ON setter is invoked and what it reads/writes before modifying anything else.

## Test
1. Force-stop Xenius. Independently confirm key40 `0` while camera is idle. Install P151K10 over same-certificate K9 (or sign unsigned variant with your existing MT Manager key).
2. Open ID5 first, check key40 READ **while Xenius is active** (do not set it manually), try one 3-frame 50 MP photo.
3. Open Additional Lenses → Camera 4 (ID9), confirm the characteristic TC preview and try one 3-frame 50 MP photo.
4. Exit Xenius and check key40 READ `0` again. Confirm stock camera works.
5. If the key still reads `0` while active or capture fails, `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K10_KEY40_TEST.txt`. Inspect `RESOLUTION_SWITCH`, `VIVO_GATE`, `RAW50_REPEAT`, `RAW50_REQ`, `onClosed`, and Camera2 exceptions.

Fallback: P151K2 remains user-confirmed stable for reliable captures, without new ID9 TC activation.