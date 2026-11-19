# Xenius P152B — ISO cap for dark 50 MP bursts (P152A + ISO cap)

**APK:** `XENIUS_P152B_ISOCAP_UNSIGNED.apk` (unsigned; sign with your K13 key). P152A is the fallback.
**Status:** structurally verified offline only. Not run on the phone yet.

## Problem
The 50 MP burst copies ISO and exposure from the frame that triggered the shot. libgcam's gain is ISO / 50 with a tuning
maximum of 48×, so dark shots went over the limit (ISO 3200 → 64×, ISO 2458 → 49×).
libgcam then warned "too much gain … beyond the maximum" and "The overall gain … will exceed the maximum. This should never happen."

## Fix
If the burst ISO is above **2400** (48×):
- ISO → 2400
- exposure → exposure × ISO / 2400, so the total brightness is unchanged
- exposure capped at **125 ms** (1/8 s) to limit handheld blur. Above that the frames are slightly darker, and HDR+ brightens them.

Examples: ISO 3200 at 40 ms → ISO 2400 at 53 ms. ISO 2458 at 30 ms → ISO 2400 at 31 ms.
Shots at ISO ≤ 2400 (daylight and most indoor shots) are completely unchanged.

## Test
1. A dark scene, RES ON, 3 and 10 frames.
2. The log should no longer contain `too much gain` / `exceed the maximum`:
   `logcat -d -v threadtime | grep -E "libgcam|merged_frame" > /sdcard/Download/P152B_DARK.txt`
3. The probe file now shows ISO 2400 with a longer exposure for those shots.
4. Compare noise and banding with the same scene on P152A. Hold steady: 10 frames at 53 ms take about 0.6 s.
