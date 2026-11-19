# Xenius-FullRes

## Current checkpoint: P152C (2026-11-19, user-tested)

Vivo X300 Ultra · LMC 8.3 / Xenius GCam · package `com.meitu.xenius135a01`.
Built from the P151K13 APK (classes.dex SHA-256 `840d6355…f5d5`) by `rebuild/P152C/build_p152c.py`.

| Feature | Status |
|---|---|
| RES viewfinder button | **OFF = original 12 MP GCam**, **ON = 50 MP FullRes**; tapping RES restarts the app (P149B) |
| key40 (vivo full-size gate) | acquired before every camera open, held while Xenius is in the foreground, released on leave/exit (P148B/P148D) |
| 50 MP HDR+ | up to **10 real frames**, each with its own metadata, merged 10/10 (P148A, P148C, P152A) |
| Low light | burst ISO capped at 2400 (GCam 48× gain) with exposure compensation, max 125 ms (P152B) |
| Overhead | capture-result leak fixed (P152A); probe file only written for burst frames (P152C) |

Known port limits (not FullRes bugs): no gyro for HDR+ (12 MP too), GCam AWB model has no entry for this sensor, 10-bit data in 16-bit RAW warning.

### Build
```bash
cd rebuild/P152C
python3 build_p152c.py /path/to/XENIUS_P151K13_MINIMAL_ID9_ONLY_V2_SIGNED.apk XENIUS_P152C_UNSIGNED.apk
```
Output is **unsigned**; sign with the same key as the installed build (e.g. MT Manager). The builders stack:
P149A → P149B → P148A → P148B → P148C → P148D → P152A → P152B → P152C; each `rebuild/<ver>/` has the script and a README
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
