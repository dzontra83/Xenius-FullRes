# Xenius P149A — RES button = 12 MP / 50 MP FullRes

**Built:** 19 Nov 2026 · **Base:** P151K13 (classes.dex SHA-256 `840d6355…f5d5`) · **Package:** `com.meitu.xenius135a01`
**APK:** `XENIUS_P149A_RES_12_50_UNSIGNED.apk` — UNSIGNED, sign with MT Manager using the same key as K13.
**Status:** structurally verified offline only. Not run on the phone yet.

## What RES does now

| RES | Mode | key40 | Session | HDR+ |
|---|---|---|---|---|
| **ON** | 50 MP FullRes | acquired (as K13) | K13 8192×6144 RAW16 reader | K13 50 MP 2/3/5F path, unchanged |
| **OFF** | 12 MP normal | **not touched** | no RAW50 reader | original GCam 12 MP / DCG path |

The RES button already saved `pref_upscale_key` and called `CameraActivity.ReInit()` (camera close + reopen).
P149A reuses that, so switching closes the camera, releases key40 via the existing K2 `Lksn.onClosed` path, and reopens
in the new mode. RES no longer applies GCam upscaling in either state.

## Exact changes (5 methods; everything else byte-identical to K13)

classes.dex
- `Llel.c` (GCam session creation): before the RAW50 reader block, reads `pref_upscale_key`. OFF → skips the
  reader, removes stale `RAW50_REQ` (closes it), `getHardwareBuffer`, `getTimestamp`, logs `RESOLUTION_SWITCH: skip`.
- `Llfe.e` (other session output lists): same gate.
- `AeShotParams.j` / `.k`: upscale target size is never applied (`if-nez` → 2× nop).

classes2.dex
- `LMC/c2a.getC2apiPref` acquire path (`null` argument, used by onCreate/onResume/`Lkti.a` pre-open):
  OFF → returns without touching key40, logs `VIVO_GATE: pref_upscale_key`. The release path (`Lksn.onClosed`) is unchanged.

The 50 MP burst (`Llei`), shutter (`BottomBarController`) and HDR+ routing (`Ldvm.E`) already skip themselves when
`RAW50_REQ` / `getHardwareBuffer` are absent, so they needed no edits.

## Offline verification
- DEX header file_size, SHA-1 and Adler-32 are valid. String, type, field and method tables are identical to K13.
- All 48,301 + 4,866 methods disassemble. In every method, branch, switch, try and handler targets land on instruction boundaries.
- Patched methods were relocated to the end of the code section and class_data was rewritten. Only the 5 methods above differ.
- APK: only `classes.dex` and `classes2.dex` were replaced. The old v1 signature files were removed. Stored entries are 4-byte aligned.
- No ART verifier, Android device or Vivo HAL is available here.

## Phone test (one variable at a time)
1. Back up XML and the K13 APK. Sign P149A with MT Manager (same key) and install over K13.
2. `logcat -c`. Open the app and check the RES state: ON = 50 MP, OFF = 12 MP.
3. **RES OFF, ID5:** take a 12 MP photo. Expect `RESOLUTION_SWITCH: skip` and `VIVO_GATE: pref_upscale_key`, a ~12 MP photo,
   and key40 = 0 while the app is open.
4. Tap **RES ON:** the preview reopens. Take a 3F 50 MP photo. Expect `RAW50_REQ: applied`, `VIVO_GATE: 1`, and an 8192×6144-based result.
5. Switch OFF → ON → OFF → ON several times, taking one photo each time. Then exit the app, check key40 = 0 and that the stock camera opens.
6. Only after that, try ID9 (TC) in both modes. 12 MP on ID9 still sends `extLensInfo`, but without key40, so it may behave differently.
7. Log: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P149A_LOG.txt`

## Known risks
- **Close/open race:** the old camera's `onClosed` sets key40 = 0. If that arrives after the new 50 MP open has acquired
  key40, the 50 MP session can fail. This is the same pattern as K13 lens switching. If a 50 MP session fails right after
  pressing RES, this is the first suspect.
- The second (50 MP) GCam instance is still created at app start in both modes, so memory use is the same as K13.
