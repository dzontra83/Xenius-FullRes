# Xenius P164B — current checkpoint

**APK:** `XENIUS_P164B_20F_UNSIGNED.apk` (unsigned; sign with your K13 key). classes.dex SHA-256
`dd43b3d2d9c90fb002a631eb95732c31b6cae22f41748d58ef079b10d6a22ea5`; classes2.dex = P155.
**User-tested:** 50 MP 20/20 and 15/15 frames merged, frame count shown in the gallery.

## What it is
P156 (flush before the 50 MP burst, original HDR+ hand-off) plus the changes that proved useful:
| From | Change |
|---|---|
| P158B + P160 | OIS mode copied from the preview into the 50 MP burst request (focus lock tried in P158B, removed in P160: vivo's reported focus distance is not a usable lens position) |
| P162 | gyro factory: GCam's DirectGyro (SensorDirectChannel, Pixel-only) -> its SensorEventListener gyro (`Llgw`) |
| P162B | HDR+ gyro gate opened (`Lied.get`: direct-channel / rate / JNI / device-flag checks skipped; gyro sensor still required). Diag P162BD: gyro provider present on every frame (was absent on all frames before) |
| P163D | EXIF Model = `<model> <merged>/<handed over> frames`, set on the ExifInterface right before the JPEG is written (`Llpy.j`), from the HDR+ merge summary (`Lohy.accept`) |
| P163E | the JPEG save waits (max 3 s) for the merge stats when an HDR+ EXIF was built (`Ldub.a` flag), so the count is always there |
| P164B | 50 MP frame cap 25 -> 20 |

Build: `python3 build_p164.py XENIUS_P156_FLUSH_UNSIGNED.apk P164.apk && python3 build_p164b.py P164.apk XENIUS_P164B_20F_UNSIGNED.apk`
(`build_p164.py` chains build_p158 -> p160 -> p162 -> p162b -> p163d -> p163e on the P156 dex).

## Findings (2026-11-20)
- **Frame cap.** `Download/merge.txt` logs (P156L): every captured frame reached HDR+ up to 20 frames (20/20, 19/19,
  18/18, 14/14, 13/13). At 25 the vivo HAL stalls (130-265 ms frame gaps) and drops frames: 25 asked -> 21 delivered.
- **P157 dropped.** Its streaming hand-off gave no speed gain: GCam's own payload frame arrives only after the burst,
  then all 50 MP frames are fed within ~40 ms. Its speed-up was the 15-frame cap. P159 only fixed P157's 12 MP wait.
- **Timing.** EXIF is built ~0.4 s before HDR+ reports merge stats; the save raced the stats (hence P163E).
- **Noise profile.** 50 MP frames report the same SENSOR_NOISE_PROFILE as the 12 MP preview at the same exposure
  (P161E diag) -> HDR+ likely under-estimates 50 MP noise. Not changed yet.
- **Shutter.** RawR vs GCam screen recordings: capture time equal (~1.65 s frozen viewfinder, preview back ~2 s);
  shutter-to-ready is mostly frame count (33-40 ms per 50 MP frame).

## Experiments kept in rebuild/ (not in the checkpoint)
P157 (streaming hand-off + 15-frame cap), P159 (P157 12 MP fix), P161D/P161E (gyro / noise-profile diagnostics),
P162BD-style diag via P161E, P163/P163B/P163C (EXIF hooks that ran too early), P163L and P156L (merge.txt log builds).
