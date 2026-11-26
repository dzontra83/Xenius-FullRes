# Xenius P148D — key40 stays on while Xenius is open (RES ON)

**APK:** `XENIUS_P148D_KEY40_FIX_UNSIGNED.apk` (unsigned; sign with your K13 key). Replaces P148C and includes all of it.
**Status:** structurally verified offline only. Not run on the phone yet.

## Why P148B/C still lost key40
P148B kept key40 on through camera closes only if `CameraActivity.onResume` had set a "foreground" mark. Your log shows that
`onResume` never runs in your launch path (no `RESOLUTION_SWITCH: onResume` line, while `onStop` does appear). So the mark
was never set, and every camera close (including the previous camera closing after the new one opened) kept setting key40 to 0.
RawR's notes say full-size capture breaks if key40 is released after the session is set up, which is the "won't start"
you saw. Opening RawR worked because RawR turned key40 back on at the right moment.

## Fix
- **RES ON: a camera close never turns key40 off.** It's released only when you leave or exit the app (`onStop`, which does run).
- key40 is turned on right before **both** camera-open paths: `Lkti.a` (already did) and now `Larb` (never did).
- Plus the 50 MP session acquire from P148B, and the metadata fix from P148C.

## If it still doesn't start
Do a fresh log of a **failed** start, so we can see the gate calls in order:
```
logcat -c
(open Xenius with RES ON, wait 5 s, try one shot)
logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P148D_FAIL.txt
```
Don't open the Key40 Switch app or RawR before saving the log. Look for `VIVO_GATE` lines; any `E VIVO_GATE` means the vendor call itself failed.
