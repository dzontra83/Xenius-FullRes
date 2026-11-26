# Xenius P151K13 — Minimal ID9 vendor request hook, stable K2 baseline
Date: 19 November 2026. Experimental isolation build; not phone-tested.

## What K12's supplied logs actually establish
- K12 log 01:26:17.569, 01:26:17.590, 01:26:17.789: three `I/VIVO_GATE: 1` entries. One `I/VIVO_GATE: 0` on camera closure at 01:26:27.623. These are setValue *attempts*; do not prove the value returned by a separate key40 read. User independently reports key40 remains 0 while app is open.
- Two native HDR+ shot attempts, shot IDs 0 and 1, fail. libgcam reports payload frame gaps 0 ms vs expected 80 ms for frames 2->3 and 3->4, no base frame candidates, and EndShotCapture failure. Six `Image is already closed` errors occur in `dvm.p` while obtaining Image.getWidth(); these were previously sometimes nonfatal, so not proof of sole cause.
- K12 probe shows real RAW Camera2 callbacks and payload finalization. This does not confirm successful native merge.

## APK code comparison
`K2 -> K9` altered four classes.dex methods:
- `Llbs.a`: session parameter
- `Laue.a`: FullRes still request builder
- `Larf.<init>`: alternate preview constructor
- `Llel.h`: actual GCam request builder
K11 added `Lksn.onOpened` key40 acquisition; K12 modified `LMC/c2a.getC2apiPref` to force acquisition attempts.

P151K13 rebuilt directly from user-confirmed stable P151K2, and adds ONLY the `Llel.h` ID9 builder hook that had triggered teleconverter-shaking preview in K9. The guard checks `CameraDevice.getId().equals("9")`; only then sets `CaptureRequest.Key<int[]>("vivo.control.extLensInfo")` to `[1,200,2]` on the GCam request builder. Method uses scratch registers without changing the live Lleo v0 reference. All K6/K7 session, still-request, alternate-preview changes are removed. No extra key40 acquisition calls or K12 conditional bypass. Original P151K2 key40 acquisition and automatic OFF-on-closed code are retained unchanged.

APK comparison: exactly `classes.dex` changed, exactly one method `Llel.h` changed. Other APK entries, including `classes2.dex`, native libraries, XML and resources, byte-identical to P151K2. DEX method control flow and exception blocks checked. APK Signed with existing Xenius development certificate and independently verified Android APK Signature Scheme v2. Android runtime verification/photo result untested.

## Test protocol — one variable
1. First install original stable P151K2, force-stop, use the same XML, open Camera ID5, measure key40 while preview is active, try a 3F 50MP photo; record photo result. Exit and check key40=0.
2. Install P151K13 and do exactly the same on Camera ID5. If it fails despite K2 working, the active builder hook alone introduces a regression.
3. Only after ID5 works, select Additional Lenses -> Camera 4 (physical Camera ID9) with the actual teleconverter attached. Is viewfinder shaky? Does 50MP 3F photo save? This minimal build omits K6 session key, so shaky viewfinder is not guaranteed.
4. Exit, ensure key40=0, test stock camera.
5. If failure, collect: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K13_MINIMAL_LOG.txt`. Observe `VIVO_GATE`, `RAW50_REPEAT`, `RAW50_REQ`, `libgcam`.

## Expected interpretation
K2 works + K13 works on ID5 -> removed extra patches likely involved; use ID9 result to decide next minimal session-only change.
K2 works + K13 fails on ID5 -> isolate shared builder hook/register side effects.
K2 also fails -> cannot attribute failure to TC patches alone; verify XML, hardware gate, camera HAL/other app state before modifying APK again.
K13 ID9 preview shaky but no capture -> investigate still-request key and native metadata rather than forcing key40 blindly.