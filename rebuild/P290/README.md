# P290 — current build

Built on top of `XENIUS_P174B_UNSIGNED.apk` (not in the repo, ask the owner):

```bash
cd rebuild/P290
export PYTHONPATH=../P149A:../P149B:../P163:../../tools/dex
OISB=off SETTLE=200 python3 build_p290.py XENIUS_P174B_UNSIGNED.apk XENIUS_P290_UNSIGNED.apk
OISB=off SETTLE=200 TBLOG=1 python3 build_p290.py XENIUS_P174B_UNSIGNED.apk XENIUS_P290L_UNSIGNED.apk   # log build
```
Output is unsigned. `libtbin.so` is prebuilt from `tbin.c` (clang line in `BUILD_SO.txt`).

## Files
| File | What |
|---|---|
| `build_p290.py` | patches classes.dex / classes2.dex (camera hooks, LMC prefs, UI), adds resources, calls `dexgen.py` |
| `dexgen.py` | generates classes3.dex: helper `TemporalBinning` (burst setup, pacing, watchdog, gyro, file tag, profiles, shutter ring) |
| `tbin.c` | JNI entry points of libtbin; includes `quad.c`, `merge.c`, `natural.c` |
| `quad.c` | quad 2x2 CFA -> Bayer remosaic: **ER** (port of Ed's RawR Detail remosaic, GPL-3.0) and **XR** (own) |
| `merge.c` | own burst pre-merge (alignment, frequency-domain robust merge), 25 MP downscale |
| `icons.py`, `textpath.py` | text icons (12 / 50 / 25, XR / ER / SR) |
| `tp288.c`, `bandsT.py`, `ghost.py`, `test_merge/` | host tests (synthetic bursts, per-band detail/noise vs a known truth) |
| `LICENSE-RAWR` | GPL-3.0 text (the ER remosaic is a port of RawR's code; libtbin is therefore GPL-3.0) |

## Remosaic button (XR -> ER -> SR)
- **XR** (own, P290): green plane by direction-weighted linear interpolation, colour differences per 2x2 block,
  bilinear between block centres. Host, clean frame, detail response per band 0.96 / 0.89 / 0.80 / 0.72
  (ER 0.99 / 0.94 / 0.86 / 0.77); about the same speed as ER.
- **ER**: Ed's Detail remosaic (RawR), best detail.
- **SR**: vivo's own remosaic.
The file name carries the tag: `IMG_<date>_XR_<suffix>.jpg` / `_ER_` / `_SR_`.

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
| `HDRCAP` | 1.5 | GCam HDR ratio cap |
| `NIGHTKEY` / `NIGHTCAP` / `NIGHTEV` | 1.7 / 1.0 / 10 | darker shot EV in dim scenes (0 = off) |
| `DARK256` | 256 | 128 = 1 EV highlight headroom (lower ISO for 50/25 MP frames) |
| `NZS` / `NZO` | 0.13 / 0.065 | GCam noise model scale for 50 MP |
| `MRG` | 1 | own pre-merge (never off in normal use) |
| `QLOW` | 3 | remosaic at low ISO when the button is on XR: 3 = XR, 0 = ER |
| `OISB` / `SETTLE` / `SETTLEN` | copy / 300 / 1500 | OIS during the burst, viewfinder hold after it (ms) |
| `TBLOG` | 0 | 1 = log build (`merge.txt`) |

## Merge (merge.c, `MG_FQ=1`)
Sharpest raw frame = reference. Global shift, 64 px tiles, affine shift field, quarter-pixel Catmull-Rom resampling.
Per tile and Bayer plane: 16x16 sin^2-windowed blocks, 2-D FFT, each frame keeps only the frequencies whose difference
to the reference is explained by noise (Wiener-type shrinkage, `MG_FQC` 64); tiles that clearly do not match are left
out. Few-frames denoise, mild detail restore, night brightening cap. Result copied into every frame of the burst.
