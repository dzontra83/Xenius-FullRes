# Xenius P158B — steady lens during the 50 MP burst

**APK:** `XENIUS_P158B_STEADY_UNSIGNED.apk` (unsigned). Built on P157. classes.dex SHA-256
`94e8d3be5541fa8eed1f14958eec28afabb72572423f972edd8fe82cd19ec50b`; classes2.dex = P155.
**User-tested:** works, photos sharp (near and far).

## Why
The 50 MP burst request is a fresh STILL_CAPTURE template; only ISO/exposure were copied from the preview. Focus and
OIS started from template defaults, so lens/OIS could re-settle as the burst began (viewfinder jumped ~40 px on P156).

## Change (`Llei.onCaptureCompleted`)
- L1 at the trigger (pc 847, `v7` = preview result): store `LENS_FOCUS_DISTANCE` and `LENS_OPTICAL_STABILIZATION_MODE`
  in System properties (removed first, never stale).
- L2 before `build()`: if a focus distance was stored → `CONTROL_AF_MODE = OFF` + that `LENS_FOCUS_DISTANCE`;
  if an OIS mode was stored → same `LENS_OPTICAL_STABILIZATION_MODE`.
- P158 (not kept) read the result at pc 936, where the ISO-cap path had overwritten `v7` (`move-result-wide v6`)
  → VerifyError on camera open. P158B reads it at pc 847.

## Measured (screen recording, P158B)
| | P156 | P158B | RawR |
|---|---|---|---|
| live preview back | +1.96 s | +1.3–1.6 s | +2.0 s |
| shutter usable | +2.3 s | +1.6–1.9 s | +1.5 s |
| thumbnail | +2.4 s | +1.75–2.1 s | +1.6 s |
| image jump at preview return | ~40 px | ~6–14 px | none visible |
