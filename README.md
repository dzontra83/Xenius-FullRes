# Xenius-FullRes

## Current checkpoint: P175F (2026-11-20) — P172 + crash fixes + 200 MP → 50 MP binned mode (Leica button) + per-mode ZSL frames

Vivo X300 Ultra · LMC 8.3 / Xenius GCam · package `com.meitu.xenius135a01`.
Chain: … → `rebuild/P172/build_p172.py` (classes.dex `6f2fb5da…6cc58`) → `rebuild/P173` (crash fixes) → `rebuild/P174`
(EXIF wait 1 s) → `rebuild/P174B` (VerifyError fix, classes.dex `00043e10…f1d8`) → `rebuild/P175/build_p175.py`
(classes.dex `3bc9dd7c…04ff`, classes2.dex `7249d30e…7cea`, new classes3.dex + lib/arm64-v8a/libtbin.so).
Details: `rebuild/P175/README.md` (200 MP mode), `rebuild/P173/README.md` (crashes), `rebuild/P172/README.md`, `rebuild/P167/README.md`, `rebuild/P165/README.md`.

| Feature | Status |
|---|---|
| RES viewfinder button | **OFF = original 12 MP GCam**, **ON = 50 MP FullRes**; tapping RES restarts the app (P149B) |
| Lenses | 50 MP on 35 mm (ID3), 85 mm (ID5) and **ultra-wide (ID4, 4096-wide RAW) since P165** |
| key40 (vivo full-size gate) | acquired before every camera open, held while Xenius is in the foreground (P148B/P148D); read back + retried (P155) |
| 50 MP HDR+ | up to **20 real frames** (cap 20 since P164B: vivo drops frames above ~20), each with its own metadata |
| Exposure | 50 MP burst copies the viewfinder exposure; ISO capped at 2400 with exposure compensation, max 125 ms (P152B) |
| Burst length | long shutters cut the frame count to keep a burst <= ~2.5 s (1/7 s → 17 frames, min 3) (P167) |
| Quiet | no toast, no Download/private log files, no fallback DNG dump (P154B) |
| Shutter | preview queue flushed before the 50 MP burst (P156); OIS mode held from the preview during the burst (P158B/P160) |
| Gyro | HDR+ gets gyro samples (normal sensor listener instead of the Pixel-only direct channel) (P162/P162B) |
| Focal length | EXIF FocalLength = 35 mm-equivalent (14 / 35 / 85 mm in Google Photos) (P168) |
| Frame count | gallery camera line shows `V2547A <merged>/<handed over> frames` for every HDR+ shot (P163D/P163E); EXIF wait max 1 s (P174) |
| 200 MP mode | RES ON + Leica ON on 35 / 85 / 200 mm: 200 MP RAW binned to 50 MP natively before HDR+, 1–3 frames one by one (P175) |
| ZSL frames | remembered per mode (12 / 50 / 200 MP) and per lens (P175F) |
| Stability | burst camera-error, unmatched-image and saved-state crashes fixed (P173/P174B) |

Known port limits (not FullRes bugs): GCam AWB model has no entry for this sensor, 10-bit data in 16-bit RAW warning.

### Build
```bash
cd rebuild/P153
XENIUS_MAXF=25 python3 build_p153.py /path/to/XENIUS_P151K13_MINIMAL_ID9_ONLY_V2_SIGNED.apk XENIUS_P153B_UNSIGNED.apk
python3 build_p154.py XENIUS_P153B_UNSIGNED.apk XENIUS_P154B_QUIET_UNSIGNED.apk
python3 build_p155.py XENIUS_P154B_QUIET_UNSIGNED.apk XENIUS_P155_KEY40_UNSIGNED.apk
python3 build_p156.py XENIUS_P155_KEY40_UNSIGNED.apk XENIUS_P156_FLUSH_UNSIGNED.apk
python3 build_p164.py XENIUS_P156_FLUSH_UNSIGNED.apk XENIUS_P164_UNSIGNED.apk
python3 build_p164b.py XENIUS_P164_UNSIGNED.apk XENIUS_P164B_20F_UNSIGNED.apk
python3 build_p165.py XENIUS_P164B_20F_UNSIGNED.apk XENIUS_P165_UW50_UNSIGNED.apk
python3 build_p172.py XENIUS_P165_UW50_UNSIGNED.apk XENIUS_P172_UNSIGNED.apk
python3 build_p173.py XENIUS_P172_UNSIGNED.apk XENIUS_P173_UNSIGNED.apk
python3 build_p174.py XENIUS_P173_UNSIGNED.apk XENIUS_P174_UNSIGNED.apk
python3 build_p174b.py XENIUS_P174_UNSIGNED.apk XENIUS_P174B_UNSIGNED.apk
python3 build_p175.py XENIUS_P174B_UNSIGNED.apk XENIUS_P175F_UNSIGNED.apk   # needs dexgen.py + libtbin.so
```
Output is **unsigned**; sign with the same key as the installed build (e.g. MT Manager). The builders stack:
P149A → P149B → P148A → P148B → P148C → P148D → P152A → P152B → P152C → P153 (P153B = P153 with `XENIUS_MAXF=25`) → P154B → P155 → P156 → P164 → P164B → P165 → P172 (P157–P163 are experiments, see rebuild/P164B/README.md); each `rebuild/<ver>/` has the script and a README
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
