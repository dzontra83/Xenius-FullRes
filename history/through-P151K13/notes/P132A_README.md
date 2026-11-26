# Xenius LMC 8.3 P132-A — shasta_zsl=true native BurstSpec diagnostic

## Purpose
P131-A FIX5 produced a **valid native BurstSpec pointer and non-null frame-request vector,
with zero native frame requests** on both 50 MP captures (`...:256`).
This P132-A changes **only the experimental native-builder call's fourth `dvm.j`
argument from false to true**, which forwards to `BuildPayloadBurstSpecOptions_shasta_zsl_set`.
This tests whether the planner mode alone is responsible for zero scheduled requests.

All other 8192x6144 RAW16 capture/staging, the two native RawWriteView instances,
matched timestamp/exposure/sensor-ID metadata, legal `dwg` constructor, cleanup,
original Google 4080x3064 payload, and native GCam libraries remain unchanged.
It does NOT inject 50 MP frames or perform HDR+ merging.

## Read `RAW50_C_PROBE1.txt` marker
- `...:0`: native pointer valid; request vector exists and has >0 requests.
- `...:256`: pointer/vector valid but still zero requests, even with shasta_zsl=true.
- `...:32`: native BurstSpec pointer low word appears zero.
- `...:128`: request vector wrapper is null.
- `...:512`: native builder returned null Java BurstSpec wrapper.
- `...:64`: caught Java exception; stack trace follows.
Additional earlier metadata error bits may combine with these codes.

## On-device test
Install `com.meitu.xenius132a01` separately with the same **older NON-DCG FullRes XML**.
Check the viewfinder, then take one 50 MP shot. Only try a second if the first finishes.
Send `RAW50_C_PROBE1.txt` and `RAW50_REQ.txt`.
P131-A FIX5 remains a phone-tested fallback; P130-A is the clean native-pair baseline.

**Static integrity verification and APK v2 signing are not a substitute for Android ART
verification or testing the actual Google native function.**