# Xenius P148C — fixes the "0 ms gap / no base frame" HDR+ abort (P148B + metadata null-fix)

**APK:** `XENIUS_P148C_HDR10_METAFIX_UNSIGNED.apk` (unsigned; sign with your K13 key). Replaces P148B.
**Status:** structurally verified offline only. Not run on the phone yet.

## What your P148B log showed (shot at 15:59:02–04)
- key40 **was working**. The 8192×6144 stream started, and 10 RAW frames arrived and filled slots 1–10.
- HDR+ then aborted:
  `timestamp gap between payload frames 2..9 = 0.0 ms` → `No base frame candidates` → `Aborting capture processing`.
- Cause: every 50 MP frame logged `ohv: Exception in converting to Gcam FrameMetadata … NullPointerException
  Integer.intValue()`. The 50 MP burst runs with manual exposure, so the HAL returns `CONTROL_AE_STATE` and
  `CONTROL_AWB_STATE` = null. `Lohv.k` (Camera2 result → GCam FrameMetadata) crashes on those, and the frames end up
  with stale, duplicated metadata. This is the same "0 ms gap" K12 hit. It also explains why more frames failed:
  the extra frames were all copies.
- key40 = 0 when you checked it: leaving Xenius runs `onStop`, which releases key40 by design
  (`RESOLUTION_SWITCH: onStop` → `VIVO_GATE: 0` 200 ms later). While Xenius is open it stays 1.

## Fix
`Lohv.k`: 10 result fields that were read without a null check now fall back to a neutral value when the HAL returns
null: AE_STATE = CONVERGED, AWB_STATE = CONVERGED, AF_STATE = INACTIVE, control/AE/AWB/AF/flash modes and triggers
= 0/AUTO. Frames that do carry these values (all normal 12 MP frames) are unchanged.

Everything from P148B is included: 10 frames, key40 held while the app is open, RES 12/50 MP.

## Test
1. RES ON, 5 frames → then 6, 8, 10.
2. The log should **no longer** contain `Exception in converting to Gcam FrameMetadata` or `0.0 ms` gaps, and should show no
   `No base frame candidates`.
3. To check key40 *while Xenius is open*, look for `VIVO_GATE` / `RESOLUTION_SWITCH: onClosed` in the log.
   Switching to the Key40 Switch app will always show 0, because leaving Xenius releases it.
4. Log: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P148C_LOG.txt`
