# Xenius P149B — RES = 12 MP / 50 MP, with the original 12 MP GCam restored

**Base:** P151K13 · **APK:** `XENIUS_P149B_RES_12_50_UNSIGNED.apk` (unsigned; sign with your K13 key in MT Manager)
**Replaces:** P149A. In P149A, 50 MP worked but RES OFF did not give back normal 12 MP GCam.

## Why P149A failed in 12 MP
K13 also hard-codes 8192×6144 into `Lohv.q`, which builds the sensor description for the **main** GCam HDR+ engine.
Every shot, 12 MP or 50 MP, goes through that engine (`Ldvm.s` → `Ldvm.j`). The engine is created only once, when the app starts.
So with RES OFF, HDR+ still thought the sensor was 8192×6144 while receiving normal 12 MP frames.

## What P149B changes
| | RES OFF (12 MP) | RES ON (50 MP) |
|---|---|---|
| `Lohv.q` sensor sizes (6 places) | **original code**: `getcustomwidth/height`, real RAW max | K13 8192 / 6144 |
| RAW50 reader (`Llel.c`, `Llfe.e`) | not created; stale state removed | K13 |
| key40 on app/camera open | **set to 0 if it isn't already** | acquired (K13) |
| Upscaling | off | off |

**Tapping RES now restarts the app** with LMC's own `LMC/main.onRestart()`, the same helper PRO, LDR and LUT use. This is
needed so the GCam engine is rebuilt for the new mode. If HDR+ is still processing, LMC shows its usual toast and
waits before restarting.

key40 release now skips the write and the 200 ms pause when key40 already reads 0. When it isn't 0, it still writes 0 as K13 does.

Changed methods: classes.dex `Lohv.q`, `Llel.c`, `Llfe.e`, `AeShotParams.j/.k`; classes2.dex `LMC/c2a.getC2apiPref`,
`Upscale$1.onCheckedChanged`. Everything else is byte-identical to K13. The original `Lohv.q` instructions come from the
P101 disassembly in the repo's source archives, not from guesses.

## Phone test
1. Install over K13 or P149A (same signing key).
2. **RES OFF:** the app should behave like the original 12 MP GCam (preview, HDR+ photo, DCG). Check the photo's resolution.
3. Tap **RES ON:** the app restarts. Take a 50 MP 3F photo.
4. Tap **RES OFF:** the app restarts. key40 should read 0. Take a 12 MP photo.
5. Repeat 3–4 a few times, then exit and check that the stock camera opens.
6. Log: `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P149B_LOG.txt`

Useful log lines: `RESOLUTION_SWITCH: skip` (12 MP session), `RAW50_REQ: applied` (50 MP session), `VIVO_GATE: 0/1`.
