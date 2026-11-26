# P151K9 ID9 Active GCam Builder — ART VerifyError Fix

## User crash evidence
The P151K8 crash report `LMC8.3_VIVO_V2547A(PD2547)_2026-11-19(1).prop` explicitly says:
`java.lang.VerifyError: Verifier rejected class lel: leo lel.h(int) failed to verify: [0x2E] tried to get class from non-reference register v0 (type=Conflict)`.
`[0x2E]` is dex code-unit 46: original `invoke-direct {v0,v3}, Lleo.<init>`, confirming that v0 must preserve the `new-instance Lleo` reference allocated at dex CU32.

## Root cause in K8
K8 inserted a vendor-key check before dex CU36 (from CU51 out-of-line), but reused **v0** for CameraDevice.getId(), String.equals result, string logs and a catch exception. At CU46, v0 was not a Lleo instance, causing ART class verification failure during CameraDevice.onOpened.

## P151K9 fix
Rebuilt FROM P151K7 to retain the original session + alternate preview + 50MP still vendor hooks and P151K2 automatic key40 OFF. In the active `Llel.h(int)` addition, v0 is never touched. Scratch registers v2,v4,v5 hold ID strings, equality, CaptureRequest.Key, vendor array, logs, and catch exception. Original `Lleo` object v0, Camera2 Builder v3 and argument v7 are preserved on every branch. Existing code and all other methods/resources/native libs byte-identical to K7. The hook remains ID9-only, writing `vivo.control.extLensInfo = int[]{1,200,2}` on the active GCam request-builder path and logging successful sets as `RAW50_REPEAT`.

## Verification
Offline DEX structural checks passed: opcode boundaries/branch targets, try/catch regions, all code items, DEX checksum, ZIP integrity. Independent APK Signature Scheme v2 RSA-SHA256 signed-data/digest verification passed with the same development certificate as P151K2. **No on-device Android runtime verifier is available** so actual install/open still must be tested.

## Test
Attach physical 200 mm teleconverter. Under Additional Lenses choose Camera 4 configured to ID9. Opening without VerifyError is first checkpoint. Look for `I/RAW50_REPEAT: ID9 extLensInfo [1,200,2] SET`, and check the actual teleconverter FOV. Then capture 50MP with 3 frames if preview activates. Confirm key40 resets OFF when app closes. Export log if crash or preview unchanged:
`logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K9_ID9_TC_TEST.txt`

P151K2 is the stable 5-frame baseline. P151K9 is experimental.