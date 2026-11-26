# P306 — current build

Built on top of `XENIUS_P174B_UNSIGNED.apk` (not in the repo, ask the owner):

```bash
cd rebuild/P306
export PYTHONPATH=../P149A:../P149B:../P163:../../tools/dex
OISB=off SETTLE=200 python3 build_p306.py XENIUS_P174B_UNSIGNED.apk XENIUS_P306_UNSIGNED.apk
OISB=off SETTLE=200 TBLOG=1 python3 build_p306.py XENIUS_P174B_UNSIGNED.apk XENIUS_P306L_UNSIGNED.apk   # log build
```
Output is unsigned. `libtbin.so` is prebuilt from `tbin.c` (clang line in `BUILD_SO.txt`).

## Files
| File | What |
|---|---|
| `build_p306.py` | patches classes.dex / classes2.dex (camera hooks, LMC prefs, UI), adds resources, calls `dexgen.py` |
| `dexgen.py` | generates classes3.dex: helper `TemporalBinning` (burst setup, pacing, watchdog, gyro, file tag, profiles, shutter ring) |
| `tbin.c` | JNI entry points of libtbin; includes `quad.c`, `merge.c`, `natural.c` |
| `quad.c` | quad 2x2 CFA -> Bayer remosaic: **ER** (port of Ed's RawR Detail remosaic, GPL-3.0); copy mode for SR 25 MP |
| `merge.c` | own burst pre-merge (alignment, frequency-domain robust merge), 25 MP downscale |
| `icons.py`, `textpath.py` | text icons (12 / 50 / 25, ER / SR) |
| `tp288.c`, `bandsT.py`, `ghost.py`, `test_merge/` | host tests (synthetic bursts, per-band detail/noise vs a known truth) |
| `LICENSE-RAWR` | GPL-3.0 text (the ER remosaic is a port of RawR's code; libtbin is therefore GPL-3.0) |

## Remosaic button (ER <-> SR)
- **ER**: Ed's Detail remosaic (RawR), then our pre-merge.
- **SR**: vivo's own remosaic. 50 MP: fully stock (GCam's HDR+ merges). 25 MP: vivo frames copied, our pre-merge and the
  50 -> 25 MP resample (GCam expects 25 MP frames there).
- The own XR remosaic was retired in P293 (colour fringes on thin high-contrast edges; ER better on every measure).
The file name carries the tag: `IMG_<date>_ER_<suffix>.jpg` / `_SR_`.

## Main options (environment variables, default)
| Option | Default | |
|---|---|---|
| `PACE` | 6 | 50 MP frames in flight |
| `WARM1` | 1 | first 50/25 MP burst after app start sends 1 frame first |
| `WDMS` | 2000 | burst watchdog (ms without a frame) |
| `LONGEXP` / `LONGEXP2` | 30 / 40 ms | frame cap handheld / steady (gyro) |
| `HHEXP` / `HHISO` | 20 ms / 400 | handheld: 1/50 s while ISO <= 400 (0 = off) |
| `NIGHTEXP` | 60 ms | night frames (OIS on) |
| `ISOCAP` / `TELECAP` | 1600 / 800 | ISO cap main+UW / tele+teleconverter |
| `HDRCAP` | 1.5 | GCam HDR ratio cap (bright light) |
| `NIGHTBASE` / `NIGHTDARK` | 0.5 / 0.0 | shot EV offset: -NIGHTBASE in bright light .. -NIGHTDARK in dim scenes |
| `NIGHTEVHI` / `NIGHTEVLO` | 8 / 3 | EV100 range of that smoothstep |
| `HDRCAPD` | 3.5 | HDR ratio cap in dim scenes (HDRCAP in bright light) |
| `ECSHORT` | -1.0 | GCam short-exposure (highlight) EC in dim scenes, EV |
| `AFVID` / `AFHOLD` | 1 / 0 | viewfinder continuous-video AF / focus hold while steady (`AFHOLDG` 0.08 rad/s, `AFHOLDMS` 1200) |
| `NOREAP` | 1 | disable GCam's background ProcessReaper |
| `DARK256` | 256 | 128 = 1 EV highlight headroom (lower ISO for 50/25 MP frames) |
| `NZS` / `NZO` | 0.13 / 0.065 | GCam noise model scale for 50 MP |
| `MRG` | 1 | own pre-merge (never off in normal use) |
| `OISB` / `SETTLE` / `SETTLEN` | copy / 300 / 1500 | OIS during the burst, viewfinder hold after it (ms) |
| `TBLOG` | 0 | 1 = log build (`merge.txt`) |

## Merge (merge.c, `MG_FQ=1`)
Sharpest raw frame = reference. Global shift, 64 px tiles, affine shift field, quarter-pixel Catmull-Rom resampling.
Per tile and Bayer plane: 16x16 sin^2-windowed blocks, 2-D FFT, each frame keeps only the frequencies whose difference
to the reference is explained by noise (Wiener-type shrinkage, `MG_FQC` 64); tiles that clearly do not match are left
out. Few-frames denoise, mild detail restore, night brightening cap. Result copied into every frame of the burst.

## Settings
Advanced > **Disable face detection** (pref key `STATISTICS_FACE_DETECT_MODE`): on -> no face detection in the requests,
so faces no longer steer GCam's AF / AE.
