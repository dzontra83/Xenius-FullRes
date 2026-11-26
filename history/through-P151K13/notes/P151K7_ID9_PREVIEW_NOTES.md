# Xenius P151K7 — Additional Lens Camera 4 (ID9) preview teleconverter experiment

## Background
The user configured **Camera 4** in the GCam **Additional Lenses** menu to **camera ID 9**. P151K6 preserved 50 MP output but its viewfinder remained stable, unlike the user's known physical teleconverter active-mode behavior. P151K6 applied `vivo.control.extLensInfo` only in the session helper and 50 MP still-request builder, and did **not** patch the central normal preview request builder.

## Base and unchanged invariants
- Built on P151K6, which in turn was based on **stable P151K2**, not on the experimental K3–K5 longer-burst builds.
- K2 `classes2.dex` (automatic key40 `0` on CameraDevice.onClosed), native libraries, resource files, 2–5-frame HDR+ capture, raw stream and DNG cleanup are byte-for-byte unchanged from K6.
- K6's separate ID9 `Llbs.a` session parameter and `Laue.a` still-capture key application are preserved unchanged.

## New ID9 preview change
- The central request helper constructor `Larf.<init>` (DEX method ID 9222) creates a `CameraDevice.TEMPLATE_PREVIEW` CaptureRequest.Builder.
- Before overwriting the `CameraDevice` argument with the request builder, K7 now calls `CameraDevice.getId()` and logs the **actual camera device ID** using `I/LMC_TC_SESSION`.
- If, and only if, the device ID equals the string `"9"`, it creates a typed `CaptureRequest.Key<int[]>` named `vivo.control.extLensInfo`, constructs `[1, 200, 2]`, and sets it on the preview CaptureRequest.Builder. The existing K6 value is already applied separately to session parameters and FullRes still capture requests.
- On successful setting, it logs `I/LMC_TC_SESSION: ID9 extLensInfo [1,200,2] SET`.
- Exceptions from key construction or `Builder.set()` are caught and logged with `E/LMC_TC_SESSION` and the exception. The app's original preview constructor continues rather than throwing for the new TC setting.
- All constructor instructions after the builder's creation are unchanged.

## Test
1. Before opening Xenius, read key40 OFF (`0`) with the key40 utility. Install signed P151K7 over same-certificate P151K2/6; if your current installation is MT Manager signed, sign the unsigned file with the same original certificate instead.
2. Attach physical Vivo 200 mm TC. In Additional Lenses, use **Camera 4 = ID9**. Open it and watch for expected distinctive teleconverter preview movement/field of view.
3. Capture one 50MP image at 3F. Verify magnification and focus rather than relying solely on viewfinder shaking.
4. Exit, verify key40 has returned to `0`, and try the stock camera.
5. Export logcat with `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K7_ID9_PREVIEW.txt`.

## Diagnostic interpretation
- If no actual device ID `9` is logged, the additional-lens menu may map its slot or camera selection to a different runtime `CameraDevice`. The printed ID helps correct the next target.
- If ID9 is logged and `SET` appears but preview behavior remains unchanged, either the repeating request is built separately/overrides this builder or Vivo requires another preview path/vendor key. Trace repeating request construction and inspect Camera2 request tags. Do **not** conclude the key is effective just because `Builder.set()` accepted it.
- If `E/LMC_TC_SESSION` logs an exception, read its details: invalid key support vs incorrect type vs different issue.

## Verification
- DEX method indices/string references, control-flow branch targets, try/catch range, DEX checksum and hash, other method byte identity, and APK ZIP integrity verified locally.
- Signed package v2 signature, certificate and chunk digests verified using independent parser; same development certificate as signed K2–K6. Standard Android `apksigner`/device test not available in this environment.
- Experimental K7: *not* a new stable baseline until on-device teleconverter and key40 checks pass.