# Xenius P151K6 — automatic ID9 physical teleconverter vendor key

## Base
- Source: user-confirmed STABLE `XENIUS_P151K2_FORCE_KEY40_OFF_ONCLOSED_UNSIGNED.apk`.
- P151K2's camera-device `onClosed` → Vivo key40 OFF policy is byte-identical (`classes2.dex`).
- Original native libraries, 50MP RAW/HDR+ 2–5 frame baseline, temporary DNG cleanup, all camera resources, and AndroidManifest are unchanged.
- Experimental version K6 is **not** K3/K4/K5's unstable 10-frame experiment.

## ID9-only modifications
1. **Session configuration:** `Llbs.a` (DEX method 44740), previously applied `vivo.control.extLensInfo` to `Lleo` session parameters only when XML `parameter_3_name` matched. Now it applies `CaptureRequest.Key<int[]>('vivo.control.extLensInfo')` with `[1,200,2]` automatically when the session camera ID string is `"9"`. ID5 and all other camera sessions remain unchanged.
2. **Full-resolution RAW capture request:** `Laue.a` (DEX method 9532) now, while building the existing FullRes RAW capture request, checks `CameraDevice.getId().equals("9")` and only then sets `CaptureRequest.Key<int[]>('vivo.control.extLensInfo')` to `[1,200,2]` on the builder. Exceptions in this extra setting reuse the original catch-all handler. Existing Vivo 50MP keys and capture flow remain intact.
3. Diagnostics: the old session `LMC_TC_SESSION` log remains; setting on RAW request produces `I/RAW50_REQ: ID9 extLensInfo [1,200,2] SET`.

## Caveat
- The request patch explicitly targets `Laue.a`'s 50 MP capture request builder. It does **not** patch every possible repeating-preview request builder in GCam. Session parameters may suffice to activate the physical teleconverter before capture; device verification is essential. If preview requires request-scoped key too, instrument/restrict the central repeating request path next.
- No test performed on a Vivo phone. The output is a valid-format APK Signature Scheme v2 development-signature package checked offline, not verified with Android `apksigner` (not available here).
- The certificate is the same experimental Xenius certificate used for signed P151K2, P151K3, P151K4 and P151K5.

## Test
1. Force-stop Xenius and check key40 = 0.
2. Install P151K6 signed APK over the existing same-development-certificate build (back up XML before uninstalling if using MT Manager's different certificate).
3. Physically attach Vivo teleconverter, select ID9, open preview, photograph 50MP 3F, check field of view and real RAW size.
4. Check logs `LMC_TC_SESSION`, `RAW50_REQ`, `RESOLUTION_SWITCH`, `VIVO_GATE`, `onClosed`, and camera errors.
5. Exit Xenius and READ key40: must be 0; verify stock camera works. Reopen and repeat once.
6. Switch to ID5 and verify 50MP without physical TC. K6 should not alter ID5.

Log collection:
`logcat -c` before the capture and after completing tests:
`logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K6_ID9_TC_TEST.txt`

## Verification
- Source-to-new APK byte comparison (everything but classes.dex identical), DEX string/method/type indices, instruction boundaries, try ranges, class_data relocation and checksum, APK archive integrity, resource alignment, RSA-SHA256 APK v2 signature+digest verified using independent parser.