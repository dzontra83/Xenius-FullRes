# Xenius P151K0 — RES/Key40 foundation, NOT a completed 12/50 switch

**Built:** 18 November 2026. **Package:** `com.meitu.xenius135a01`.  
**APK:** `XENIUS_P151K0_RES_GATE_FOUNDATION_UNSIGNED.apk`; sign with MT Manager.

## Scope (exact)

This is the first experimental foundation. It is **still 50 MP FullRes only**. The RES button is **not yet connected** to the special 8192×6144 stream or to key40. The point is to identify the camera close path safely before implementing dynamic camera reconfiguration. The key40 helper is unchanged.

Based on `XENIUS_P151J_TEST2_REENTRY_GATE_RECHECK_UNSIGNED.apk`:

1. **classes2.dex**: **byte-identical** to TEST2. Analysis clarified that the apparent `add-int/lit8 v4,v4,1` uses `v4=getInfo(40)` rather than the in-process `Aemodef` counter. Replacing it with a constant would be a redundant change on the normal acquire branch, so we deliberately did **not** patch it. The unresolved restoration failure remains.
2. **classes.dex**: add `I RESOLUTION_SWITCH: onResume` at the start of `CameraActivity.onResume` (then retain original TEST2 key activation).
3. **classes.dex**: add `I RESOLUTION_SWITCH: onStop` at the start of `CameraActivity.onStop`. Note: Android `onStop` does not prove that a CameraDevice has actually closed.
4. **classes.dex**: add `I onClosed: onClosed` when `Lksn.onClosed` executes, before its pre-existing gate release and RAW50 ImageReader cleanup. The alternate camera route `Larb/Laqx` does not necessarily use this callback.

All RAW50 callbacks, 50 MP output, native HDR+ 2F/3F/5F merge and FIX2 DNG cleanup method bytes are preserved. AndroidManifest, resources and 20 native libraries unchanged.

The original Activity.onResume activation is **still global** in this APK. This probe does NOT switch key40 off whenever the viewfinder hides. We have specifically avoided forcing OFF on Activity.onStop, because that can race with Camera2 device shutdown or in-progress processing.

## Live test

1. Back up your XML and signed working APK. Fully close Xenius; when no camera uses the device, use the independent switch to set OFF and READ `0`.
2. Sign/install this experimental APK with MT Manager (same package name).
3. `logcat -c`
4. Open Xenius, take two 50MP 3F shots, leave Xenius normally. Read key40 **without changing it**; check whether stock camera opens.
5. If gate remains `1`, **do not assume this build has fixed it**. Export the log immediately and send it. If stock camera must be restored, close Xenius and set OFF using the independent key40 utility when the camera is idle.
6. Before returning to Xenius, you can change the RES control and note its displayed value, but this build does not use it to choose a stream.

LADB export:

```sh
logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K0_FOUNDATION.txt
```

How to interpret the sequence:
- `RESOLUTION_SWITCH: onResume` followed by `VIVO_GATE: 1` = activity entered and gate requested (vendor readback independently still required).
- `RESOLUTION_SWITCH: onStop` **without** `onClosed: onClosed` = the instrumented `Lksn` close callback did not run in the visible log; the alternate `Laqx` path may be in use, or the event might have been dropped from logcat.
- `onClosed: onClosed` + `VIVO_GATE: 0` = original helper attempted to release to 0; confirm with the independent switch.
- `onClosed: onClosed` + `VIVO_GATE: 1` = inspect marker / saved previous value; it may have been 1.

## Next integration milestones

- Map **actual RES viewfinder selection event** (not just the camera settings' `pref_camera_resolution`, which may mean a different setting on this build).
- Create serialized state coordinator (design source `P151K_RES_MODE_COORDINATOR_DESIGN.kt`) with `CLOSED / OPENING / ACTIVE / CLOSING`, requested 12/50 mode, camera generation tokens, pending-capture drain, and gate lease.
- Implement 12 MP normal session and 50 MP FullRes session as separate opening recipes, not an in-place change of an already-configured Camera2 stream.
- Route `onClosed` from **both** normal and alternate `Larb/Laqx` paths into the coordinator, and restore verified previous key40 value only after final close.
- Verify 12→50→12 repeatedly, rapid tapping, app leaving during processing, initial key40=0 or 1, unexpected camera error, and stock camera recovery.

## Offline verification

- ZIP CRC, two DEX SHA1/Adler32 checksums and all referenced method code offsets validated.
- Prefixed Dalvik instruction boundaries/relative branches validated; no try blocks in target methods.
- For `onStop`, increased DEX code_item outs_size 1→2 to accommodate the two-argument Log.i call.
- Only method bodies `CameraActivity.onResume`, `CameraActivity.onStop`, `Lksn.onClosed` changed; the key40 helper and every other preexisting method are byte-identical to P151J TEST2.
- No Android device runtime/ART or Vivo HAL available in this environment, so these are **structural checks**, not a claim of successful on-device capture or installability without user signing.