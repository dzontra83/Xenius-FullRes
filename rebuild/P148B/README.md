# Xenius P148B — key40 held while Xenius is open (+ P148A 10-frame HDR+, + P149B RES 12/50)

**APK:** `XENIUS_P148B_HDR10_KEY40HOLD_UNSIGNED.apk` (unsigned; sign with your K13 key). Replaces P148A.
**Status:** structurally verified offline only. Not run on the phone yet.

## The key40 bug (present since K2)
K2/K13 set key40 = 0 on **every** `Lksn.onClosed`. GCam also closes and reopens the camera while the app is still open
(lens and mode switches, session rebuilds), and its alternate `Larb` open path never turns key40 back on. When the
old camera's close arrives after the new open, key40 stays 0 and 50 MP silently fails until something else, such as
RawR, sets it to 1 again.

## Fix (RawR's VendorCameraGate rule: hold the gate while the full-size camera is in use)
| Hook | RES ON | RES OFF |
|---|---|---|
| `CameraActivity.onResume` | mark app as in the foreground; acquire key40 (as before) | key40 → 0 if needed (P149B) |
| `Lksn.onClosed` (any camera close) | **keep key40** while in the foreground; RAW50 reader still closed | release, as before |
| `CameraActivity.onStop` (leave or exit app) | clear the mark, **release key40** | clear the mark |
| 50 MP session setup (`Llel.c`/`Llfe.e`) | **acquire again before every configure** (no write if already 1) | – |

Log lines: `RESOLUTION_SWITCH: onClosed` = key40 kept on a camera close; `VIVO_GATE: 1` / `0` = actual writes.

## Test
1. RES ON. Switch lenses (ID5 ↔ others ↔ ID9), modes and settings several times, taking a 50 MP shot after each.
   key40 should stay 1 the whole time (check with your Key40 Switch app).
2. Press Home or exit: key40 → 0 within about a second. The stock camera must open normally.
3. Reopen Xenius: key40 → 1 and 50 MP works without RawR.
4. RES OFF: key40 0, 12 MP normal.
5. Frame counts as in the P148A notes (5 → 6 → 8 → 10).
6. Log: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P148B_LOG.txt`

## Known limits
- If Xenius crashes while RES is ON, key40 stays 1 until Xenius is reopened (RES OFF resets it) or the Key40 Switch is used.
- Leaving the app in the middle of a 50 MP burst releases key40 during the capture. Wait for the shutter to finish.
