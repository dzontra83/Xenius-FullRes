# Xenius P155 — key40 gate: verify and retry

**APK:** `XENIUS_P155_KEY40_UNSIGNED.apk` (unsigned; sign with your K13 key). Built on P154B.
classes2.dex SHA-256 `2e37dbbda927b81e1a8c0940973480390d3c4a130c4cbc6be0d733aade2d1589`; classes.dex = P154B.

## Why
A second user had the old symptom on the latest build: sometimes no 50 MP pictures until RawR had set key40.
The gate (`LMC/c2a.getC2apiPref`) wrote `setValue(40, 1)`, slept 200 ms and assumed it worked. `setValue` is a
one-way Binder call; RawR's `VivoFullSizeGate` reads the value back before opening the camera.

## Change
After `setValue(40, target)` + 200 ms the gate reads key40 back; if it isn't the target it writes again and
re-checks, up to 3 attempts 300 ms apart. Log: `VIVO_GATE <value read back>`, or `VIVO_GATE -1` if key40 never
took. The gate already runs before every open (P148D) and right before the 50 MP session (P148B K4), so key40
is verified at both points. Release (RES OFF) is verified the same way.

## If it still fails
`logcat -d -v time | grep -E "VIVO_GATE|RESOLUTION_SWITCH|setUseVivoCamera|AppType|Function not implemented|configureStreams"`
`VIVO_GATE 1` + failure → next step is RawR's VCF variant (key33 = 2, restored on exit). `VIVO_GATE -1` → something
resets key40.
