# Xenius P160 — focus lock removed, OIS copy kept (current checkpoint)

**APK:** `XENIUS_P160_NOAFLOCK_UNSIGNED.apk` (unsigned). Built on P159. classes.dex SHA-256
`30d9336bbd86e082c1b9adaf850362878e65fb7d93aa1bb1aff572173278efcf`; classes2.dex = P155.
**User-tested:** 50 MP sharper than P158B/P159.

## Why
P158B locked focus for the 50 MP burst: `CONTROL_AF_MODE = OFF` + the preview result's `LENS_FOCUS_DISTANCE`.
On vivo the reported focus distance doesn't match the real lens position, so the lens was parked slightly off;
far scenes looked fine, nearer subjects went soft.

## Change (one string index, in place)
The burst-build step looks the stored focus distance up under a key that is never set (`LENS_FOCUS_RANGE`), so AF mode
and focus distance stay as the STILL_CAPTURE template has them (pre-P158B). The OIS-mode copy from P158B stays.
