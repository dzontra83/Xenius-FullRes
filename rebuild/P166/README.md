# P166 — 50 MP burst follows LMC "HDR++ exposure" (pref_aemode_key, per lens)

Base: P165 (classes.dex `a99b8203…3240`). Output classes.dex `6c80df4e3a2f7b642cb33704a5f4e7f2c342d2cdfa91bc16b742a729825eecf4`.

## Before
The 50 MP burst copied ISO + exposure of the trigger (viewfinder) frame; if ISO > 2400 it moved to ISO 2400 with a longer
exposure (max 125 ms). LMC's Exposure menu ("HDR++ exposure": Max ISO / ISO 1600..100 / Max Time / Time 32 s..1 ms) only
reached GCam's own HDR+ frame requests (`Lohv.p`), never the burst.

## Change (Llei.onCaptureCompleted, right after abortCaptures)
If `LMC/pref.MenuValueLens("pref_aemode_key") != 0` (and `LMC/AeMode.iso100 > 0`):
```
sGetDesired_exposure_time_ms = exposure_ns / 1e6
sGetDesired_analog_gain      = ISO * iso100 / 100     (gain units, 1.0 = sensor min ISO)
sGetDesired_digital_gain     = 1
LMC/AeMode.isoTimeParametrs(mode)                     (LMC's own math: same total exposure; ISO modes cap time at
                                                       "Maximum exposure time", Time modes put the rest in gain)
exposure_ns = time_ms * 1e6 ; ISO = round(analog * digital * 100 / iso100)
```
and the 2400 / 125 ms rule is skipped. Auto keeps the old rule.

## Phone test (2026-11-20, P166L2 log build, 85 mm indoors)
| mode | burst ISO / shutter | frame spacing | HDR+ SNR | EXIF |
|---|---|---|---|---|
| ISO 400 | 400 / 76 ms | 76 ms | 38.5 | 15/15, 1/13 s |
| Time 1/7 s | 247 / 142.9 ms | 143 ms | 49.7 | 15/15, 1/7 s |
| Auto | 1370 / 30 ms | 33 ms | 20.3 | 15/15, 1/33 s |

The vivo HAL honours the requested 50 MP exposure. Daylight: all modes end at base ISO 50 with the needed shutter.

`build_p166l2.py` (on the P165L2 log base → P166L → P166L2) adds an `exif <ISO> <exposure ns>` line per burst to Download/merge.txt.
