# P320 — current build

Built on top of `XENIUS_P174B_UNSIGNED.apk` (not in the repo, ask the owner):

```bash
cd rebuild/P320
export PYTHONPATH=../P149A:../P149B:../P163:../../tools/dex
OISB=off SETTLE=200 python3 build_p320.py XENIUS_P174B_UNSIGNED.apk XENIUS_P320_UNSIGNED.apk
OISB=off SETTLE=200 TBLOG=1 python3 build_p320.py XENIUS_P174B_UNSIGNED.apk XENIUS_P320L_UNSIGNED.apk   # log build
```
Output is unsigned. `libtbin.so` is prebuilt from `tbin.c` (clang line in `BUILD_SO.txt`).

## Files
| File | What |
|---|---|
| `build_p320.py` | patches classes.dex / classes2.dex (camera hooks, LMC prefs, UI), adds resources, calls `dexgen.py` |
| `dexgen.py` | generates classes3.dex: helper `TemporalBinning` (burst setup, pacing, watchdog, gyro, file tag, profiles, shutter ring, AE meter, XML loader `TBXL`) |
| `tbin.c` | JNI entry points of libtbin; includes `quad.c`, `merge.c`, `natural.c` |
| `quad.c` | quad 2x2 CFA -> Bayer remosaic: **ER** (port of Ed's RawR Detail remosaic, GPL-3.0); copy mode for SR 25 MP |
| `merge.c` | own burst pre-merge (alignment, frequency-domain robust merge), 25 MP downscale, output scale with highlight knee |
| `icons.py`, `textpath.py` | text icons (12 / 50 / 25, ER / SR), folder icon + 'XML loader' setting |
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
| `AEMETER` | 1 | own AE meter (below); 0 = P306 behaviour |
| `AEFLOOR` | -1.5 | lowest total shot EV offset (night key + meter) |
| `AECAPK` | 1.0 | how strongly the meter's midtone term lowers the dim-scene HDR cap |
| `AEMERGEK` | 1.0 | strength of the meter darkening applied as merge output scale |
| `AEHEAD` | 1 | highlight headroom: lower 50/25 MP frame ISO when the viewfinder raw clips |
| `TBLOG` | 0 | 1 = log build (`merge.txt`) |

## Merge (merge.c, `MG_FQ=1`)
Sharpest raw frame = reference. Global shift, 64 px tiles, affine shift field, quarter-pixel Catmull-Rom resampling.
Per tile and Bayer plane: 16x16 sin^2-windowed blocks, 2-D FFT, each frame keeps only the frequencies whose difference
to the reference is explained by noise (Wiener-type shrinkage, `MG_FQC` 64); tiles that clearly do not match are left
out. Few-frames denoise, mild detail restore, night brightening cap. Result copied into every frame of the burst.

## Settings
Advanced > **Disable face detection** (pref key `STATISTICS_FACE_DETECT_MODE`): on -> no face detection in the requests,
so faces no longer steer GCam's AF / AE.

## Own AE meter (P310-P315, `AEMETER=1`)
GCam keeps a binned 12 MP raw stream (4080 x 3064) running while framing, also in 50 / 25 MP. Every RAW16 frame passes
`Llet.<init>`; the helper gets `Pair(image, image)` and `N.e()` meters ~3 frames/s (4x4 tiles on a 128x96 grid: median,
mean, centre, p99 / p99.5 of the tile max, clipped share). Terms (native defines in `tbin.c`):
- midtone: median above `AE_TGT` 0.045 -> darken, down to `AE_MIN` -1 EV, weighted by the night-key smoothstep
  (dim scenes only); highlight guard p99 > 0.84 -> up to `AE_GMIN` -0.5 EV;
- applied as (a) extra shot EV, (b) lower dim-scene HDR cap, (c) **merge output scale** (`nightS`, GCam does not lift
  it back; `pm_knee`, `PM_KNEE` 0.6, keeps clipped pixels at white - plain scaling turned lamps pink, P313);
- highlight headroom (P315): clipped share >= 0.1 % -> 50 / 25 MP frame ISO x 2^-(0.5 log2(1 + clip/`AE_HC` 40)),
  at most `AE_HMAX` 1 EV (shorter frame below ISO 50); GCam brightens back to its plan, the glow keeps its gradient.
Shot EV and the HDR cap alone barely change GCam's output brightness (its own target wins) - the raw-level scale is what works.
Log: `ae w=... | ev base= guard= matrix= ... | xmed= xgrd= hs256=`, shot `own AE merge scale s256=`, request `head=`.

## XML loader and import fix (P316-P320)
- LMC's config load copies the XML over the settings file, then `onRestart -> apply()` saves `pref_config_show` and
  writes the old in-memory settings back -> the first import did nothing. Fix: profile helper 95 (before the copy)
  remembers the file and commits the flag; 98 (restart) writes the chosen file over the settings after LMC's write,
  verifies 3 x, unpacks its 12/50/25 profiles and leaves a note; 94 (Upscale button init) toasts
  `XML loaded: <name> (N mode profiles)`.
- LMC's **Aperture** button is the **XML loader** (setting renamed, folder icons): added to the top row (`OpenPref`, after
  Watermark; the layout's own Aperture is hidden); one tap lists `/LMC8.3/XML/*.xml` newest first (LMC's comparator),
  current one marked; a tap loads it (95 + 98), restarts. Its switch is global: profile restore / import keep the
  current `pref_show_button_aperture`.
