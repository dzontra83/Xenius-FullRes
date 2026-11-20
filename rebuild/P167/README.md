# P167 — burst-length cap for long exposures

Base: P166. Output classes.dex `9ec4515c489c6a4821cbdb67a3029ac64a7498e8503c99b353c091f623d5f81b`.

With HDR++ exposure Time modes the 50 MP burst can run long (20 x 1/7 s ≈ 2.9 s). P167 keeps a burst at <= ~2.5 s:

* where the burst ISO / exposure are final (before `props.put("ISO")`):
  `props["SENSOR_EXPOSURE_TIME"] = Integer(max(3, (int)(2.5e9 / exposure_ns)))`, removed if there is no exposure;
* at the frame-count clamp (before `props["pref_hdrnet_key"] = count` and the capture loop): `count = min(count, value)`.

Examples: <= 125 ms → unchanged (20 max), 1/7 s → 17, 1/4 s → 10, 0.5 s → 5, >= 0.84 s → 3 frames.

Phone test (2026-11-20): 85 mm, 20 frames set, Time 1/7 s → gallery shows 17/17 frames. UW 50 MP distortion matches 12 MP.
