# Xenius P152C — probe file only for 50 MP frames (P152B + probe fix)

**APK:** `XENIUS_P152C_UNSIGNED.apk` (unsigned; sign with your K13 key). Includes everything up to P152B.
**Status:** structurally verified offline only. Not run on the phone yet.

## P152B result (from your probe file)
- The ISO cap works. A night trigger at ISO 12800 / 70 ms became an ISO 2400 / 125 ms burst. 3- and 10-frame shots merged, with 10/10 not aborted.
- Daylight bursts are unchanged.

## Fix in P152C
The same probe file showed that after each 50 MP shot, *every preview frame* (30/s) was appended to
`Download/RAW50_C_PROBE1.txt` on the main thread until the next shot. That's 180 lines in 6 s between two of your shots. K13's probe
writers in `Llei.onCaptureStarted` / `onCaptureCompleted` stayed active as long as `RAW50_REPEAT` was set, which is permanent
after the first shot. They now write only for the 50 MP burst frames (listener-less callback), so the probe file stays
useful for checking bursts but goes quiet during preview.

## Expected
- `RAW50_C_PROBE1.txt` grows by about 2 lines per burst frame plus a few per shot. No long `onCaptureStarted:…:0/1/2` runs.
- The viewfinder might feel slightly smoother after the first 50 MP shot.
- Everything else is the same as P152B.
