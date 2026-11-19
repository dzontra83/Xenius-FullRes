# Xenius P148A — 50 MP HDR+ up to 10 frames (includes P149B RES 12/50 MP)

**Base:** P151K13 + P149B · **APK:** `XENIUS_P148A_HDR10_RES_UNSIGNED.apk` (unsigned; sign with your K13 key)
**Status:** structurally verified offline only. Not run on the phone yet. P149B stays the fallback.

## Why it was capped at 5
It was not a native GCam limit. K13's frame handoff had room for exactly 5 frames:
- `Llei.onCaptureCompleted` clamped the ZSL-frames setting to 2–5.
- `Lleu.onImageAvailable` stored each 50 MP frame in one of **5 named slots** and **closed frame 6+**.
- `Ldvm.p` fed slots 1→5 into HDR+ and stopped at the first empty slot. Feeding could also start before the
  later frames had arrived, so frames could be skipped or come in the wrong order (K12's "0 ms gap / no base frame").
K3 raised only the clamp and K4 only the buffer count. Neither added slots, so every frame above 5 was still thrown away.

## Changes (on top of P149B)
| Where | Change |
|---|---|
| `Llei` clamp | 2–10 (invalid value → 5, as before) |
| `Llei` burst start | removes and closes stale frames left in any of the 10 slots |
| `Lleu` producer | slots 6–10 added before an overflow frame is closed |
| `Ldvm.p` consumer | slot order extended to 10 frames |
| `Ldvm.p` first frame | waits (max 3 s, 10 ms steps) until frame N has arrived, so all N are fed in order. Never waits on the UI thread |
| RAW50 ImageReader | maxImages 5 → 10 |

The 2/3/5-frame behavior is unchanged. With all frames already present the wait is 0 ms, and slots 1–5 work as in K13.
P149B (RES 12/50 MP) is unchanged. classes2.dex is byte-identical to P149B.

## Phone test (stop at the first failure)
1. RES ON, ID5, **5 frames:** regression check. It must work as before.
2. **6 frames**, then **8**, then **10**: one shot each, letting processing finish before the next shot.
3. Check the log for the merged count: `ShotLogData_merged_frame_count_get` / `merged_frame_count` and `aborted=false`.
   A saved JPEG alone doesn't prove N frames were merged.
4. Repeat the highest working count 3×, then try ID9.
5. RES OFF: a 12 MP shot must still be normal.
6. Log: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P148A_LOG.txt`

## Risks
- Memory: 10 × 96 MiB RAW frames are held at once, plus HDR+ working memory. If 10 crashes or freezes, use 8.
- If a frame never arrives (HAL drop), the first-frame wait times out after 3 s and merges what it has.
- If GCam calls the consumer on the UI thread, there's no wait, and frames above 5 may still come in short.
  The log will show this as a merged count below N.
