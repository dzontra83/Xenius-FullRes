# Xenius-FullRes

## Current checkpoint: P159 (2026-11-20) — P156 + streaming HDR+ hand-off, 15-frame cap (P157) + steady lens during the burst (P158B) + 12 MP speed fix (P159)

Vivo X300 Ultra · LMC 8.3 / Xenius GCam · package `com.meitu.xenius135a01`.
Built from the P151K13 APK (classes.dex SHA-256 `840d6355…f5d5`) by `rebuild/P153/build_p153.py` with `XENIUS_MAXF=25` (= P153B, user-tested),
then `rebuild/P154B/build_p154.py` (classes.dex `b3482bca…cbca`), `rebuild/P155/build_p155.py` (classes2.dex `2e37dbbd…1589`),
`rebuild/P156/build_p156.py` (classes.dex `b4c95194…ec35`), `rebuild/P157/build_p157.py` (classes.dex `b6926409…82e9`)
`rebuild/P158B/build_p158.py` (classes.dex `94e8d3be…c50b`) and `rebuild/P159/build_p159.py` (classes.dex `5f24d4d4…99c5`).

| Feature | Status |
|---|---|
| RES viewfinder button | **OFF = original 12 MP GCam**, **ON = 50 MP FullRes**; tapping RES restarts the app (P149B) |
| key40 (vivo full-size gate) | acquired before every camera open, held while Xenius is in the foreground, released on leave/exit (P148B/P148D) |
| 50 MP HDR+ | up to **15 real frames** (cap 15 since P157; 25 in P153B–P156), each with its own metadata (P148A, P148C, P152A, P153B); save time up to ~30 s at 20–25 frames |
| Low light | burst ISO capped at 2400 (GCam 48× gain) with exposure compensation, max 125 ms (P152B) |
| Overhead | capture-result leak fixed (P152A); probe file only for burst frames (P152C); per-frame debug logging off, no 50 MP engine in 12 MP mode (P153) |
| Quiet | no RAW50_REQ toast, no Download probe file, no private log files, no ~100 MB fallback DNG dump (P154B) |
| key40 | value read back after every write, up to 3 attempts; `VIVO_GATE 1` / `-1` in logcat (P155) |
| Shutter | preview queue flushed (`abortCaptures`) before the 50 MP burst: first exposure ~355 → ~250 ms (P156); frames handed to HDR+ as they arrive, shutter usable ~+1.6–1.9 s (P157); focus/OIS held at the preview's values during the burst, no viewfinder jump (P158B) |

Known port limits (not FullRes bugs): no gyro for HDR+ (12 MP too), GCam AWB model has no entry for this sensor, 10-bit data in 16-bit RAW warning.

### Build
```bash
cd rebuild/P153
XENIUS_MAXF=25 python3 build_p153.py /path/to/XENIUS_P151K13_MINIMAL_ID9_ONLY_V2_SIGNED.apk XENIUS_P153B_UNSIGNED.apk
python3 build_p154.py XENIUS_P153B_UNSIGNED.apk XENIUS_P154B_QUIET_UNSIGNED.apk
python3 build_p155.py XENIUS_P154B_QUIET_UNSIGNED.apk XENIUS_P155_KEY40_UNSIGNED.apk
python3 build_p156.py XENIUS_P155_KEY40_UNSIGNED.apk XENIUS_P156_FLUSH_UNSIGNED.apk
python3 build_p157.py XENIUS_P156_FLUSH_UNSIGNED.apk XENIUS_P157_STREAM15_UNSIGNED.apk
python3 build_p158.py XENIUS_P157_STREAM15_UNSIGNED.apk XENIUS_P158B_STEADY_UNSIGNED.apk
python3 build_p159.py XENIUS_P158B_STEADY_UNSIGNED.apk XENIUS_P159_12MPFIX_UNSIGNED.apk
```
Output is **unsigned**; sign with the same key as the installed build (e.g. MT Manager). The builders stack:
P149A → P149B → P148A → P148B → P148C → P148D → P152A → P152B → P152C → P153 (P153B = P153 with `XENIUS_MAXF=25`) → P154B → P155 → P156 → P157 → P158B → P159; each `rebuild/<ver>/` has the script and a README
with the root cause, the exact changes and the phone test. Builders import each other, so copy all `rebuild/*/build_*.py`
plus `tools/dex/` into one folder (or set `PYTHONPATH`). `tools/dex/` holds the DEX reader/disassembler (`dex.py`),
the code-item editor and DEX relocation (`dexpatch.py`) used by every build.

---

## Previous checkpoint: P151K13 (2026-11-19)

See [development checkpoint](history/through-P151K13/CHECKPOINT.md), [historical test notes](history/through-P151K13/notes/), and [the complete source bundle index](history/through-P151K13/SOURCE_BUNDLE_INDEX.md).

Earlier P25–P31 source archives and GitHub Actions workflows remain as originally committed.

**Source backup:** All 184 source ZIPs after P31 through P151K13 are archived byte-for-byte in `source-archives/through-P151K13/`. The signed 84.95 MB P151K13 APK is not in GitHub; its SHA-256 is documented.

## Rebuild P151K13 from P151K2

See [the verified K2-to-K13 DEX patch and rebuild script](rebuild/P151K13/README.md). The script's reconstructed APK ZIP contents match K13, but the rebuilt APK must be signed separately.
