# Xenius P156 — flush before the 50 MP burst 

**APK:** `XENIUS_P156_FLUSH_UNSIGNED.apk` (unsigned; sign with your K13 key). Built on P155.
classes.dex SHA-256 `b4c951943d952f47f47b9c1a25c7713f71590a2fdb961067625c18e50020ec35`; classes2.dex = P155.
**User-tested:** works, "a tad quicker".

## How the 50 MP shot starts
Shutter (`BottomBarController$1.onShutterButtonClicked`) sets `applied = 6`; the next preview result in
`Llei.onCaptureCompleted` makes it 7 and starts the burst: ISO/exposure copied from that result (ISO cap P152B),
`session.stopRepeating()`, N single `capture()` calls to the RAW50 reader, then the preview repeating request is restored.

## Change
`stopRepeating()` → `abortCaptures()` (one method index). The flush drops the preview requests already queued in
the HAL (it also clears the repeating request), so the 50 MP frames don't wait behind them.

## Measurements (Latency Lab P36/P37, branch `p31-stream-lab`, ID 5, burst 10, 8192x6144)
| Before the burst | shutter → 1st 50 MP exposure |
|---|---|
| nothing (DIRECT) | ~373 ms |
| stopRepeating (Xenius ≤ P155) | ~354 ms |
| **abortCaptures (P156)** | **~247 ms** in 2 of 3 runs (one run 364 ms) |
| 12 MP still first, burst after its result | ~536 ms |
50 MP frame period 40 ms (25 fps) on ID 5 and ID 3: 10 frames span 0.36 s, 25 frames ~1 s. Preview gap ~40 ms
(no sensor-mode blackout). ~250 ms is the HAL pipeline floor. Zero shutter lag at 50 MP is not possible (50 MP
frames only on request). Fewer frames shorten the hold-still time.
