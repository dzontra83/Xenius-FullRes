# P31 — GCam native RAW payload ingress hook (15 November 2026)

Status: **Binary patch assembled and locally v2-signed; not yet installed or tested on V2547A; NOT 50MP HDR+.** Stable P24 and validated P29/P30 are unchanged.

## Reverse engineered from original Xenius P24 LMC8.3

- DEX call site: `Ldvm.p(Ldxh;, I, Lljm;, Llju;, Llju;, Lniz;)`, bytecode PC **0x248**. `invoke-static/range` calls `Lcom/google/googlex/gcam/hdrplus/HdrPlusInterface;->addPayloadFrame(J,I,J,J,J,Ljava/lang/Runnable;,J,Ljava/lang/Runnable;,J,Ljava/lang/Runnable;)Z`. This is the actual per-frame RAW ingress, not the burst setup method `Gcam_BeginPayloadFrames`.
- In `libgcastartup.so`, `HdrPlusInterface_init` registers the `addPayloadFrame` JNI handler located at **0x10697A0** (seen in disassembly near init **0x1068940**). That handler calls the internal native engine at **0x1070F30**.
- ARM64 JNI registers at the handler: `x2` = Gcam pointer, `w3` = sensor ID, `x4` = RAW view pointer, `x5` = FrameMetadata pointer. Further callbacks and metadata are passed via `x6/x7` and stack.
- GCam `RawReadView.width` accessor maps to inner function **0x209FCE4**; `height` to **0x209FD40**. In nonempty views, these read offsets `+0x18` and `+0x30` respectively. This needs on-device confirmation for the real per-frame view.

## P31 diagnostic APK

- Native entry patched at **0x10697A0** to jump to a 174-byte ARM64 trampoline in verified empty executable padding at **0x2275744**. It logs `GCAM_ADD_PAYLOAD sensor=%d view=%p raw=%lldx%lld` under tag `XENIUS_HDR31`, restores input registers and returns to handler after replaying the overwritten prologue instruction.
- Separate package **`com.xenius.hdrprobe031`**; display label **XENIUS HDR TRACE P31**. Uses an independent test signing certificate, so P24 stays installed.
- Only four APK entries changed: AndroidManifest.xml, classes.dex (package string and checksum), resources.arsc (package string), and lib/arm64-v8a/libgcastartup.so. Inside the native library, differences are limited to the hook instruction and injected log-only trampoline. P24's DCG, JPEG corrections, and HDR+ merge code are otherwise untouched.
- Local checks: ZIP CRC OK, v2 signing structure/digest/signature OK, DEX SHA1 and Adler32 OK. **Cannot claim an Android installation or successful photo until phone test.**

## Phone test

Install separate P31. Take one ordinary 12MP HDR+ photo on D85 and one on D35. From LADB (adb shell), collect:
```sh
logcat -d -s XENIUS_HDR31:I | tail -60
```
Expect some `GCAM_ADD_PAYLOAD sensor=... view=... raw=<width>x<height>` lines. If none, send complete log and exact launch/capture behavior.

## Actual FullRes HDR+ work remaining

1. Configure Vivo key40 + FullRes Camera2 session **inside GCam**, without losing 12MP DCG path.
2. Convert the two verified P30 50MP Android `HardwareBuffer` frames into GCam's `RawReadView` struct in the same process. Cross-app pointer transfer is invalid.
3. Construct matched `FrameMetadata` for each sensor timestamp (10-bit actual signal, stored RAW16, RGGB, black ~64, white 1023), and meet `addPayloadFrame` ownership/release callback ABI.
4. Extend frame dimensions and validate native merge memory/geometry limits; check 2 **different** raw frames are accepted and real merged DNG/JPEG is generated. Only then call it HDR+.
5. Later repeat at F85/F35 200MP once H50 bridge merges correctly.

The P31 source ZIP is generated in ChatGPT workspace; it contains assembler, APK patch script, local v2 signer and DEX trace scripts. It does **not** contain a private key.
