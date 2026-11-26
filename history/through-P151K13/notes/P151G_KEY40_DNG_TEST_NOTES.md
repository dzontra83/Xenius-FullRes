# Xenius P151F / P151G isolated on-device test — November 18, 2026

## Important installation separation
- **Working baseline unchanged:** `XENIUS_P151C_5FRAME_OFFLINE_LOGS_SIGNED.apk`, package `com.meitu.xenius135a01`.
- **Experimental test app:** package `com.meitu.xenius151f01`, with its **own** persistent developer signing certificate. It is designed to coexist with P151C and not overwrite its camera data or XML configurations.
- Both P151F and P151G test APKs are signed with the SAME experimental certificate. P151G can replace P151F while retaining test-app preferences. They CANNOT be used to update the original P151C package, because its original private signing key is not available here.
- Install P151F test first; import the same working non-DCG FullRes XML; try ordinary 50 MP 3-frame main and tele photographs and check no new `RAW50_REQ*.dng` files appear. Only if stable, install P151G test over the P151F test app.

## P151F isolated test
- Baseline P151C native 50MP 2–5F HDR+ paths preserved.
- `Lleu.onImageAvailable` bypasses the diagnostic temporary DNG exporter, leaving `Image.getHardwareBuffer()` and the native merge untouched.
- No automatic deletion: old DNG files in other app packages or created previously are not touched.

## P151G adds experimental Vivo key40 lifecycle
The existing Xenius key40 helper (`LMC/c2a.getC2apiPref`, classes2.dex) now:
- Keeps the current `VivoCameraManager.getInfo(40)` / `setValue(40, value)` reflection API.
- Stores the original key40 value in a private `SharedPreferences` journal **before** requesting key40=1. It uses the `VIVO_GATE` file and key.
- If the process previously died while leaving a journal, and key40 still reads 1, uses the journaled previous value rather than incorrectly remembering 1 as the original.
- Encodes the original key40 value and active acquisition count in the existing static `LMC/main.Aemodef` marker, preventing one normal camera close from restoring key40 while a second gate is still retained.
- Uses the method's `synchronized` access flag to serialize concurrent helper calls.
- Restores the previous key40 value and clears the private journal on the final normal release; the original 200ms settle call is retained.

Camera lifetime call sites:
- Removes premature enable in `CameraApp.<init>` (Application constructor), which was prior to an actual camera open.
- Preserves existing `Lkti.a` pre-open acquire and `Lksn.onClosed` release (the ordinary modern opener path).
- Adds a matching pre-open acquire in the alternate `Larb.handleMessage` Camera2 opener.
- Adds releases after the two `Larb` paths invoke `CameraDevice.close()` and return; the Java close callback in this path does not override `onClosed`.

### Limitations / risks
- This is an experimental approximation of the RawR gate ownership model, **not** a full port of RawR's native device-close and idle-camera recovery logic.
- The alternate `Larb` path restores after Java `CameraDevice.close()` returns, not after an observed `onClosed` callback. This may be earlier than ideal on some firmware.
- The stale journal is read when this test app later acquires the camera, not by a background recovery service. It does not verify camera idleness before attempting to hold or recover the shared vendor key.
- There is **no independent getInfo(40) readback after setValue**, and app-specific runtime startup, state races and physical 50 MP buffer contents have not been verified on the Vivo device.
- Vendor key40 is global; do not run this test simultaneously with the stock Vivo camera or another FullRes camera app. If an image shows only a quarter of the frame, stop testing and use the original P151C baseline.
- Nothing here changes key1, key33, DCG sensor-mode keys, black level, white level or the native HDR+ merge. The physical TC / ID9 path is still separate.

## Safety-oriented test sequence
1. Keep original P151C installed. Install P151F test clone and import the known-good FullRes XML. Take one 3F main photo, then one 3F ordinary tele photo.
2. Ensure actual JPEGs are full-size and contain content across the entire image. Run:
   ```sh
   find /sdcard/Android/data/com.meitu.xenius151f01/files -maxdepth 1 -type f -name 'RAW50_REQ*.dng'
   ```
   No output after new photos confirms no new debug DNGs.
3. Update the test clone by installing P151G. Start with one 3F main photograph and one normal tele photograph; verify actual JPEG content, not just resolution metadata.
4. Close the camera normally, reopen, repeat 3F. Also test 2F and 5F only if 3F is stable.
5. In LADB, export the key gate / crash log:
   ```sh
   logcat -d -b all -v threadtime | grep -Ei 'VIVO_GATE|VivoCameraManager|VerifyError|AndroidRuntime|FATAL EXCEPTION|Fatal signal|com.meitu.xenius151f01' > /sdcard/Download/P151G_GATE_LOG.txt
   ```
6. If P151G fails, reinstall P151F test APK over it (same certificate/package) and leave P151C untouched. If the test package is unstable, stop using it rather than force-stopping during a camera session.

## Build verification
- Both generated APKs: ZIP integrity check passed, JAR/v1 signature verified, Android APK v2 digest and RSA signature independently verified.
- P151G: DEX static parsing and executable instruction boundaries verified for all four modified methods; no invalid branch targets; classes2 has three properly ordered try regions; class_data and DEX map offsets reconstructed and parsed.
- Code-body comparison versus P151C: 3 modified methods in classes.dex (`Larb.handleMessage`, `CameraApp.<init>`, `Lleu.onImageAvailable`) and 1 in classes2.dex (`LMC/c2a.getC2apiPref`).
- **On-device Android installation and actual key40 behavior are not yet verified.**