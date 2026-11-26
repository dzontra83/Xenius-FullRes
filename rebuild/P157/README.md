# Xenius P157 — streaming hand-off to HDR+, 15-frame cap

**APK:** `XENIUS_P157_STREAM15_UNSIGNED.apk` (unsigned). Built on P156. classes.dex SHA-256
`b6926409f7065c89e8f29c7bdc86cd8fdc23b178eab6cedf75dd67b129a982e9`; classes2.dex = P155. **User-tested:** "works better".

## Why
Screen recordings (RawR vs P156, same scene) showed the capture itself is equally fast: viewfinder frozen ~1.65 s,
live preview back at ~2.0 s in both. GCam lost ~0.8 s afterwards: shutter usable +2.3 s (RawR +1.5 s), thumbnail
+2.4 s (RawR +1.6 s). The HDR+ feeder (`Ldvm.p`) waited for the **last** 50 MP frame before handing frame 1 to HDR+,
then fed all N back-to-back; GCam only finishes the capture (shutter ready) after that.

## Changes (`Ldvm.p`, `Llei.onCaptureCompleted`)
- S1 first-frame wait: slot 1 instead of slot N (same 10 s timeout).
- S2 slot 1/2 occupancy markers are read, not removed, so the image listener can't put a later frame back into slot 1/2
  mid-burst (it fills the first empty slot). Llei's burst-start cleanup still clears them.
- S3/S4 slot 2 and slots 3..25: wait up to 3 s for each frame, then feed it. Slots 3+ are taken with
  `put(slot, "applied")` instead of `remove(slot)` (atomic; the placeholder keeps the slot from being reused).
  The burst-start cleanup removes placeholders (it only closes `Image` objects).
- F frame cap 25 → 15 (frame settings above 15 shoot 15; ~0.4 s shorter freeze).
