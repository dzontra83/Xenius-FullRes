# P31: GCam HDR+ native payload-ingest probe

**Date:** 2026-11-15. **Status:** APK built offline, Android v2 signature/digest and APK CRC verified, **not yet tested on device**. This is a diagnostic **not a 50MP HDR+ implementation**.

## Discovery in Xenius P24 LMC8.3

- `HdrPlusInterface.addPayloadFrame(long, int, long, long, long, Runnable, long, Runnable, long, Runnable): boolean` is a native method in `classes.dex` (`com.google.googlex.gcam.hdrplus.HdrPlusInterface`).
- Its sole analyzed DEX caller is **obfuscated `Ldvm;->p(Ldxh; I Lljm; Llju; Llju; Lniz;)V`**, code item file offset `0x416534`, method index `22463`, invoke near 0x125 DEX code units.
- In `dvm.p`, the `Llju` frame wrapper exposes an **Android `HardwareBuffer`** through `Llju;->f()`; the code invokes `AndroidJniUtils.getAHardwareBufferPtr(HardwareBuffer)` and sets up RAW-frame objects/metadata. This is the concrete bridge interface to target, rather than inventing a new `Gcam_AddRawFrame` API.
- `HdrPlusInterface.init` in `libgcastartup.so` registers the string **`addPayloadFrame`** (rodata virtual offset `0x1da18b`) with the native function at **`0x10697a0`** (ARM64 file offset equals virtual address here).
- The GCam HDR+ engine is already demonstrated merging 10/10 or 15/15 ordinary ~12MP DCG frames in P24. P30 separately captures 2 matched **8192x6144** 10-bit-in-RAW16 full-res frames per camera, but does not call GCam.

## P31 instrumentation (standalone app)

- Based on **unaltered functional P24** except a single Arm64 hook, Android app label, and package-name clone.
- New Android package **`com.xenius.hdrtracep31`**, distinct from P24 `com.meitu.meiyancamit9`; resource and DEX package strings updated at same length. DEX SHA1/Adler32 recomputed.
- ARM64 entry `0x10697a0` branches to unused executable cave `0x2275744`; trampoline executes displaced first instruction, preserves x0-x17/x30, logs `XENIUS_P31: PAYLOAD cam=%d x4=%p x5=%p x6=%p`, resumes `0x10697a4`.
- Original `__android_log_print` call via PLT `0x2273f80`. Both the P24 JPEG RGB patch and original ShotParams hook remain byte-identical. No RAW samples, metadata, or merge logic changed.
- Separate new RSA debug key/certificate; Android APK Signature Scheme v2 RSA-SHA256. **Offline verified**, not installed/run on device.
- File: `XENIUS_P31_GCAM_PAYLOAD_TRACE.apk`, **SHA256 3570ba944e9b5082443de066df6bdc62119a38a59a18c21264f5c93169b6cb37**; ZIP includes APK + README.

## First user test

1. Install P31 alongside P24 / P29 (separate package ID). If cloning issues cause a crash, **do not uninstall P24**; capture failure log instead.
2. LADB/ADB: `logcat -c`.
3. Open **XENIUS GCAM TRACE P31**, take one **ordinary ~12MP HDR+ image** with D85, then another with D35.
4. LADB/ADB: `logcat -d -s XENIUS_P31:V | tail -n 80` and share output.
5. Expect multiple `PAYLOAD` messages if this code path is exercised. A successful capture plus messages verifies native RAW callback hook. It does **not** prove 50MP HDR+.

## Next implementation if test passes

- Recover exact `Llju` `HardwareBuffer` geometry, ownership and release callbacks at `dvm.p` and compare to P30's two 50MP RAW captures.
- Implement a **conditional full-res Camera2 session** for H85/H35, including Vivo key40, separate 8192x6144 still RAW, correct Bayer metadata Black≈64 White=1023 and per-frame timestamps/ISO/exposure; leave P24 normal DCG unchanged.
- Route matching `AHardwareBuffer` payloads through **existing** `dvm.p -> HdrPlusInterface.addPayloadFrame` under the shot's `BeginPayloadFrames` lifecycle. A Java object or jlong alone is not enough: ownership, pixel stride/format, per-frame metadata, callback timing and native memory layout must match.
- Start with 2 x 50MP; verify actual `merged_frame_count=2/2` on a full-res output. If native rejects layout/dimensions, keep DNG fallback and log failure. **Do not claim HDR+** until native merge is measured.

## Safety

Package clone / unsigned modifications in third-party native GCam remain experimental; a compile+offline signature check does not prove Android install success or device behavior. No P24 or P29 installation was modified.
