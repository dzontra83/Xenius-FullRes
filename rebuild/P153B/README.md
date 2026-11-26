# Xenius P153B — speed-up + 50 MP HDR+ up to 25 frames

**APK:** `XENIUS_P153B_SPEED_25F_UNSIGNED.apk` (unsigned; sign with your K13 key). Built on P152C. **P152C stays the checkpoint.**
**Status:** structurally verified offline only. Not run on the phone yet.

## Speed
- **Debug logging off in per-frame paths.** Your P148B log had about 1,000–1,900 app log lines per second while shooting.
  202 `Log.i/Log.d` calls in the capture callbacks (`Laqv/Laqw/Laqz/Llei`), request dumps (`Laue.a`, `Lleo.a`),
  image listener, HDR+ feeder (`Ldvm.*`), metadata (`Lohv.o/p`) and LMC's `CCT_WB` (`CurrentTemp`/`CCT_dump`) are now no-ops.
  **Kept:** `VIVO_GATE`, `RESOLUTION_SWITCH`, the merge summary, and all `Log.e/Log.w` errors.
- **12 MP mode no longer builds the 50 MP GCam engine** at app start. Expect a faster start and less RAM with RES OFF.
- The probe file is unchanged (burst frames only), so you can still check shots with it.

## 25 frames (tested in P153 up to 25 frames: captured and processed, save time up to ~30 s)
- Frame setting cap 2–25, 25 frame slots, RAW50 ImageReader maxImages 25, first-frame wait up to 10 s.
- Memory: 30 × 96 MiB ≈ **2.9 GB of RAW buffers** held at once, plus HDR+ working memory. RawR reports the vivo
  camera provider crashing at 16 queued full-size frames on the global model. GCam's tuning may also limit
  payload frames. If it fails, the camera service restarts, and lower frame counts still work.
- If the LMC frames menu doesn't offer 30, pick its highest value (the menu had 12 and 25 in earlier tests).

## Test order (stop at the first failure, and note it)
1. RES OFF: 12 MP photo. Does the app start faster?
2. RES ON: **10 frames** (regression check; must match P152C).
3. **15**, then **20**, then **25/30**, one shot each in good light, waiting for each to save.
4. After each, run `logcat -d -v threadtime | grep -E "merged_frame|libgcam.*(Fatal|abort|Abort)|lowmemorykiller|FATAL"`.
5. If the camera freezes or the app is killed: note the frame count, force-stop Xenius, and check key40 (set it to 0 if needed).

## P153B vs P153
The only change is the frame cap: 30 → 25 (slots, clamp and maxImages). On P153 you shot bursts of 11–25 frames with no
crash and acceptable save times (up to about 30 s). Build: `XENIUS_MAXF=25 python3 build_p153.py <K13.apk> <out.apk>`.
