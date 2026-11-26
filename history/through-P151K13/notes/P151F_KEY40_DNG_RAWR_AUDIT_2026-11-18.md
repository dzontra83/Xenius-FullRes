# P151F engineering audit — DNG export suppression + Vivo key40 lifecycle

**Date:** 2026-11-18  
**Target:** Vivo X300 Ultra · Xenius LMC 8.3 · 50 MP FullRes HDR+  
**Proven baseline:** `XENIUS_P151C_5FRAME_OFFLINE_LOGS_SIGNED.apk`  
**Scope:** task 1 (remove RAW50 temporary DNG files) and task 4 (fix Vivo key40 lifecycle).  
**Status:** static source/DEX investigation and DNG *payload patch* completed; **no new device-tested or correctly signed P151F APK has been produced**.

## 1. Temporary RAW50_REQ*.dng files: writer found

In P151C `classes.dex`, method **`Lleu.onImageAvailable` (method ID 45140)** acquires a RAW Image and writes a diagnostic temp DNG using:

- code-unit (CU) 46: `Image.getPlanes()` starts the diagnostic RAW byte-buffer path;
- CU 90: prefix `RAW50_REQ`;
- CU 92: `File.createTempFile()` in `getExternalFilesDir(null)`;
- CU 98: `FileOutputStream.<init>`;
- CU 109: reads the bundled `dng` header asset;
- CUs 123 / 143: writes header and plane bytes;
- CU 160: closes the debug output stream;
- CU 254: **the separate `Image.getHardwareBuffer()` path** continues downstream processing.

There is **already a GOTO path** in the original P151C method: CU 36 `goto/32 -> CU 254`, bypassing the debug exporter. Therefore bypassing the diagnostic export does not inherently require any alteration to HDR+ or ImageReader lifetime handling. A minimal 3-CU patch at CU46 replaces `Image.getPlanes()` with `goto/16 -> CU254`, followed by one `nop` to preserve all code offsets. This leaves `acquireNextImage`, `Image.close()` handling, native capture/merge, fixed levels, camera keys and JPEG writing intact.

**Created payload:** `P151F_DNG_NODIAG_classes.dex`, produced by `p151f_skip_raw50_temp_dng.py`. DEX checksum and SHA1 updated. Only six code bytes (plus 28 checksum/hash-related bytes) differ from the P151C DEX. Static class parsing passed. This is **not proof of Android verifier success or on-device behavior**, and is not yet an installable APK.

## 2. RawR's verified key40 implementation

Source: user-provided `rawr-main.zip`:

- `app/src/main/kotlin/com/rawr/camera/integration/VendorCameraGate.kt`, lines 62–173, 182–202: `android.hardware.vivocamera.VivoCameraManager.getInstance()`; `getInfo(40)`; `setValue(40,1)`; wait ~100ms; readback; save original key40 value in SharedPreferences journal; restore original value on release; stale-state recovery when cameras idle.
- `app/src/main/cpp/camera/SessionRecipe.h`, lines 86–90: dedicated full-resolution **photoStream** means `GateHold::UntilClosed` (the HAL can rebuild its full-size pipeline for still captures).
- `app/src/main/cpp/camera/CameraDeviceSession.cpp`: gate acquired before camera opens (lines 336–347), acquired again if necessary just before session configuration (702–708), released immediately after configuration only for `UntilConfigured` (715–718), otherwise released **after camera device close has actually returned** (871–875). Pending closes are coordinated before reopening (320–334).
- `key33` (`VCFAppType=2`) is an **optional alternate gate**, not a default necessity. `key1` (`AppType`) is read-only in plain gate. Do not blindly set either.

## 3. Existing Xenius key40 mechanism — concrete DEX observations

P151C `classes2.dex` method **`LMC/c2a.getC2apiPref` (ID 646)** includes reflected `VivoCameraManager` calls. CUs 350–476 obtain an instance, read key40 using `getInfo(40)`, use `setValue(40,value)`, wait 200 ms and log with tag `VIVO_GATE`. Field **`LMC/main.Aemodef`** tracks an in-process previous-value marker (used only by this method in classes2.dex). It is **not** a crash-persistent preferences journal.

Callsites in `classes.dex` include:

- `CameraApp.<init>` method ID 15539, CU4, passes null to `getC2apiPref` (special enable path).
- `Lkti.a` method ID 43648, CU24, passes null **before** `CameraManager.openCamera` at CU38 (one existing pre-open gate path).
- `Lksn.onClosed` method ID 43577, CU27, calls `getC2apiPref` with a specially constructed object (the restore path) after a camera closed.
- `Llel.h` method ID 45085, CU11, calls the gate helper while building requests.
- A separate Camera2 open path exists: `Larb.handleMessage` method ID 9201, `CameraManager.openCamera` at CU692. This path does not visibly call the `LMC/c2a` gate helper immediately before its `openCamera` call.

**Important:** This confirms Xenius does already attempt a *partially similar* enable/restore scheme; the outstanding risk is inconsistent global ownership across open paths, asynchronous session transitions, crashes, and unrelated 12 MP routes. Do **not** simply sprinkle extra `setValue(40,1)` calls, or automatically force `setValue(40,0)` after each shot.

## 4. Recommended implementation for the next testable APK

Create one synchronized app-level `VivoFullResGate` owner (use the existing reflection API), with retained state `{previousKey40, changedByUs, cameraGeneration, activeDeviceCount, persistedJournal}`. The gate belongs to **FullRes device lifetime**, not per RAW frame, Camera2 request, ZSL count, or JPEG callback.

1. On selecting a FullRes lens **before either camera open path**, acquire the gate, record original `getInfo(40)` in a committed preferences journal, call `setValue(40,1)`, wait 100–200 ms and verify `getInfo(40)==1`. If acquire fails, fail FullRes explicitly; never silently reinterpret a 12MP stream as 8192x6144 RAW.
2. Keep key40 enabled through stream creation, all 2/3/5 RAW captures, session recreation and native merge. Normal non-FullRes DCG routes must not inherit a FullRes gate inadvertently.
3. Release after actual `CameraDevice.onClosed`/completed close, with refcount/generation tracking so a closing old camera cannot restore key40 while a new FullRes camera is already opening. Restore the *previous value*, not necessarily zero.
4. On error/disconnect/failed open, close any created device then release. On next process startup, recover a stale gate only if journal confirms we left it and all cameras are idle; never change shared key40 while another camera app is active.
5. Integrate or bypass the old `Aemodef` helper to avoid conflicting ownership; keep its request-settings behavior intact where it has other responsibilities.
6. Log stage, lens/camera ID, previous/current key40 (and read-only key1/key33), session creation, device-close completion, and actual image metadata `Image.getWidth/getHeight`, HardwareBuffer width/height, strides and `SENSOR_TIMESTAMP`. A quarter-screen picture could indicate a 4080-wide mode copied into an 8192-wide output, but that remains a hypothesis until buffer dimensions and sensor mode are recorded.

## 5. Proposed on-phone validation matrix

- FullRes main camera: cold open, 2F/3F/5F photos, repeated sessions, close, reopen; confirm 8192x6144 image contents.
- Ordinary tele: repeat tests and verify camera ID/stream dimensions.
- Normal 12 MP/DCG: no regression; Black/White Levels unchanged.
- Force-stop after acquisition and reopen: stale gate restoration/ownership without overwriting another camera's state.
- Fail/incompatible mode: app explicitly logs failure, never returns an apparently full-resolution quarter-frame JPEG.
- DNG suppression: no newly generated `RAW50_REQ*.dng`, but normal JPEGs and native `merged_frame_count`/`aborted=false` still work.

## APK signing blocker

The exact P151C signing keystore (`.xenius_p147_signing.p12` used in prior build sessions) is not present among the files mounted in this session. The certificate stored in the APK contains **no signing private key**. Creating a newly signed APK of the same package with another certificate would require uninstalling the working app and could lose its settings. This audit deliberately does **not** label an unsigned DEX payload as an installable update.