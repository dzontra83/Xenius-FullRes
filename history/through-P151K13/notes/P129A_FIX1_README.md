# P129-A FIX1 — simultaneous native 50MP view + FrameMetadata pair lifetime probe

Base: phone-tested P128-A FIX2, which successfully staged two independent 8192×6144 RAW16 buffers (100663296 bytes each) with timestamp-matched Camera2 metadata; JNI-mapped 8-byte sample roundtrip, both native views nonempty, temporary FrameMetadata actual exposure float readback. Existing 12MP Google HDR+ payloads remain untouched.

At the P126-B native dual-view point (Ldvm.s PC 0x405), BEFORE either native view gets released, this variant creates **two additional native FrameMetadata objects simultaneously**. Native `FrameMetadata_sensor_id_set` receives 5 (previously observed `StaticMetadata_sensor_id_get:5`), then both `FrameMetadata_sensor_id_get` values are compared against 5. Both metadata wrappers are explicitly released, the two RAW views are re-checked with empty(), and both are explicitly destroyed. The existing Google `Gcam_BeginPayloadFrames/addPayloadFrame/Gcam_EndShotCapture` sequence is unchanged. It tests the 4-object co-lifetime and sensor-id JNI readback; it does NOT populate real exposure/timestamps in this simultaneous pair (the original P128-A temporary metadata probe still validates exposure separately). It does NOT call `Gcam_BuildPayloadBurstSpec`, `addPayloadFrame` with 50MP data or execute HDR+ merging.

FIX1 verifies the exceptional return edge: on a thrown Java exception in the concurrent native probe, both v2 and v3 are initialized to integer value 1 before the original Integer.toString logging block at PC 0x40B. Previously, the handler jumped from a state where v2 might still be a wide pointer, so Android 17 verifier rejected the whole method at PC 0x40B. No native library changes. On fallback, old dual-view marker may be `1:1` and new sensor ID marker absent. This is *only* a bytecode verifier fix.

New marker in `/sdcard/Download/RAW50_C_PROBE1.txt`:
`getBuffer:FrameMetadata_sensor_id_get:<mask>`
Mask 0 = both readbacks equal 5; 1 = first mismatch; 2 = second; 3 = both.
Then the existing P126-B/P127-A/P128-A markers must also appear:
```
getBuffer:new_RawWriteView__SWIG_1:0:0
getBuffer:FrameMetadata_actual_exposure_time_ms_get:0
getBuffer:getDirectBufferAddressImpl:0
```

This is an experimental native JNI lifetime test; even with static DEX and signing checks, ART verifier, native execution and file I/O are unverified on-device. Install side-by-side with package `com.meitu.xenius129a02`; keep P128-A FIX2 as working fallback. Use **non-DCG XML** only. Check viewfinder, take ONE 50MP photo, and a second only if first completes. Send `RAW50_C_PROBE1.txt` and `RAW50_REQ.txt`. Black preview/hang => LADB full logcat. Do not modify Black/White Level or DCG settings.

## Test the verifier fix

The uploaded P129-A log showed `java.lang.VerifyError: dvm.s ... [0x40B] register v2 has type Conflict but expected Integer`. The new exception handler sets **both v2 and v3 to integer 1** before jumping to the inherited 0x40B log block, which requires `Integer.toString(v2)` and `Integer.toString(v3)`. These registers can otherwise be a 64-bit pointer pair during exception propagation.

**If** the native probe throws, the marker `getBuffer:FrameMetadata_sensor_id_get:0` may be absent and the previous `getBuffer:new_RawWriteView__SWIG_1:1:1` indicates the fallback. In that case, stop testing, use P128-A FIX2, and send logcat. Since the native view wrappers may not be released in that exception path, do not continue capturing on a failed probe.

Expected successful sequence for each test shot:
```
getBuffer:FrameMetadata_sensor_id_get:0
getBuffer:FrameMetadata_actual_exposure_time_ms_get:0
getBuffer:getDirectBufferAddressImpl:0
getBuffer:new_RawWriteView__SWIG_1:0:0
... Gcam_EndShotCapture ...
```

Native nonempty status is not proof Google HDR+ can consume 50 MP pixel data. Google's 4080x3064 addPayloadFrame call remains unchanged.