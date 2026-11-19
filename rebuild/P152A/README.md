# Xenius P152A — every 50 MP frame is now a real, distinct frame (+ memory leak fix)

**APK:** `XENIUS_P152A_UNSIGNED.apk` (unsigned; sign with your K13 key). Includes P148D (key40, 10 frames, RES, metadata fix).
**Status:** structurally verified offline only. Not run on the phone yet. P148D is the fallback.

## Items 1 + 3: duplicate frames (the real cause of "0.0 ms gap", missing gyro and unknown sharpness)
In your P148B log, frames 2–9 each failed with `IllegalStateException: Image is already closed`. K13's image listener
put each new 50 MP frame into a slot and then **closed it unless it was in slot 1 or 2**. The HDR+ feeder found closed
images in slots 3+ and fell back to re-adding the *previous* frame. So "10/10 merged" was really frames 0–2 plus
copies of frame 2. That's why the timestamps were identical, gyro was missing and sharpness was unknown. K13 had the same
problem at 5 frames (only ~3 real frames).
**Fix:** a frame stored in *any* of the 10 slots stays open until HDR+ takes it.

## Item 5: debug overhead
- **Memory leak fixed.** After the first 50 MP shot, *every* capture result (preview at 30 fps) was stored in System
  properties and never removed. Only listener-less still-capture (burst) results are stored now, which are exactly
  the frames HDR+ looks up.
- The per-frame MediaStore probe in the image listener is unreachable code, so it costs nothing.
- The remaining probe-file writes run a few times per shot, inside blocks mixed with real logic, so they're left alone.
  The cost is small next to the ~3.8 s merge.

## Items 2 + 4: not FullRes bugs
- *"Unable to find color transformation … Using driver AWB"*: the sensor colour calibration is passed to GCam
  correctly, but GCam's AWB model has no entry for this vivo sensor. This is a limit of the port.
  LMC's AWB/JAWB options are the way to tune colour.
- *"expected 10 bits, got 16"*: 10-bit data in a 16-bit container. It's a warning only, and the merge handles it.

## What a good log looks like now (10 frames)
- No `Image is already closed`, no `E RAW50_REQ: addPayloadFrame()`
- `RAW50_REQ: onCaptureCompleted` about 10× per shot (each frame found its own result)
- No `0.0 ms` gaps, and far fewer `gyro data is missing` / `unknown sharpness` lines
- `merged_frame_count = 10` (or fewer, if HDR+ itself rejects blurry frames, which is now possible because they're real frames)
```
logcat -d -v threadtime | grep -E "libgcam|merged_frame|already closed|addPayloadFrame\(\)|RAW50_REQ: onCaptureCompleted" > /sdcard/Download/P152A_MERGE.txt
```
