# Xenius P151K8 — ID9 active GCam preview-request patch

**Purpose:** Respond to P151K7 failing to activate the Vivo X300 Ultra physical 200 mm teleconverter on Additional Lenses Camera 4 (configured to `CameraDevice` ID `9`).

## Evidence from user's P151K7 log
- 00:41:09.710: `I LMC_TC_SESSION: Session builder entered` and `ID9 extLensInfo [1,200,2] SET` — K6/K7 session setter executed successfully.
- 00:41:09.718: `I createCaptureRequest: vivo.control.extLensInfo : 1, 200, 2` once in the log, but subsequent `setRepeatingRequest` lines had no observed TC behavior.
- **No K7 central `Larf.<init>` preview ID logging** — that constructor was evidently not exercised for this camera path.
- 00:41:09.794 onward: `RAW50_REQ: 33` — logs emitted from `Llel.h` demonstrate this GCam-specific request-builder method is active.
- 00:41:14.694: `VIVO_GATE: 0` — stable K2 camera-close behavior remains operative.

## P151K8 changes (EXPERIMENTAL)
- Based on P151K7, inheriting P151K2's stable 2–5-frame native 50 MP HDR+ and automatic key40 OFF on camera closure.
- **Patches active `Llel.h`**, DEX method `45085`, an instance method wrapping `CameraDevice.createCaptureRequest` and returning a `Lleo` builder wrapper used by GCam.
- Reads `CameraDevice.getId()` from its own field when a new capture request builder is created.
- Only when the device ID string is exactly `"9"`, applies a Camera2 vendor `CaptureRequest.Key<int[]>` named `vivo.control.extLensInfo`, with values `[1, 200, 2]`.
- Prints `I/RAW50_REPEAT: ID9 extLensInfo [1,200,2] SET` on success, and `E/RAW50_REPEAT: vivo.control.extLensInfo` with exception on failure. A try/catch catches only the new vendor-key constructor and set operation. The original request-builder, metadata, and handler behavior remain untouched.
- Retains K6/K7's existing ID9 session and alternate request hooks (which did not suffice for viewfinder activation).
- **Caveat:** The experimental RAW50 burst capture branch in `Llei.onCaptureCompleted` directly creates a separate Camera2 request builder, so K8 does NOT yet prove that the TC key reaches every individual FullRes still-frame request. First priority is confirming preview/repeating requests; if preview works but still capture does not, that separate burst-builder path should be instrumented next.

## APKs
- `XENIUS_P151K8_ID9_GCAM_REQUEST_TC_V2_SIGNED.apk` — signed with same Xenius experiment certificate as K2/K6/K7.
- `XENIUS_P151K8_ID9_GCAM_REQUEST_TC_UNSIGNED.apk` — for MT Manager signing if required.

## Suggested test
1. Attach physical 200 mm teleconverter, use Additional Lenses → Camera 4 = ID9.
2. Check whether preview now shows the TC field of view / characteristic movement, compared with K7; do not use wobble alone as definitive proof of magnification.
3. Check one 3-frame 50 MP still photograph if preview works. If photo does not have TC magnification, report the discrepancy — K8's FullRes RAW burst builder has not been patched directly.
4. Verify key40 OFF when exiting Xenius and that stock camera reopens.
5. LADB logcat: `logcat -c` before opening, then `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K8_ID9_GCAM_REQUEST.txt` after test. Look for `RAW50_REPEAT`, `LMC_TC_SESSION`, `createCaptureRequest`, `setRepeatingRequest`, `VIVO_GATE`.

## Offline verification
- Only `classes.dex` is changed relative to K7; `classes2.dex`, native `.so`, resources and all unrelated APK entries byte-identical.
- DEX instruction boundaries, branch targets, original and new typed/catch-all handler structures, DEX SHA-1/Adler32, APK ZIP integrity, 4-byte resource alignment checked.
- RSA-SHA256 APK v2 signature verified by independent parser and digest check using the existing certificate. Android on-device installation and operation unverified.

**Known stable baseline remains P151K2. This is not a stable release.**