# P165 — 50 MP on the ultra-wide (ID4)

Base: P164B (classes.dex `dd43b3d2…2ea5`). Output classes.dex `a99b82034b00949b8fe4464473e80c307a0af4fa88efdf76afb2cb0c36973240`.

## Problem
On the UW (camera ID4, LMC slot back_3) with 50 MP on, the shutter gave no picture. The P165L log showed the
8192x6144 reader was added to the session (`applied`), but a shutter press only handed 5 ZSL frames to HDR+:
no `capture` line (burst never started), no 50 MP frames, no merge (HDR+ waited for 50 MP frames forever).

## Root cause
`Lkyu.get` stores GCam's 12 MP RAW ImageReader as `props['rejected']` only when its width is exactly 4080
(ID3 / ID5). The shutter hook (`BottomBarController$1.onShutterButtonClicked`) arms the burst (`applied = 6`)
only if that reader is stored. The UW RAW stream is **4096**x3072 (same as RawR's H14 route), so the burst was
never armed.

## Change
`Lkyu.get`, before the `if-nez v31` after `width - 4080`:
```
add-int/lit8 v32, v31, -16   # width - 4096
if-nez v32, +4
const/16 v31, 0              # 4096 counts as 4080
```
No other lens is affected (no other code checks the camera ID or 4080 width).

## Phone test (2026-11-20, P165L2 = P165L + this fix)
UW 50 MP: `capture 4`, 15 x `image 8192x6144` (frame count set to 15 for the lens), merged 15/15 in 4.5 s, photo saved.
85 mm unchanged (19/19 merged in the P165L run).

## Build
`python3 build_p165.py XENIUS_P164B_20F_UNSIGNED.apk XENIUS_P165_UW50_UNSIGNED.apk`
(also accepts the P165L log build → P165L2, classes.dex `d14d1ccb…4df2`).
