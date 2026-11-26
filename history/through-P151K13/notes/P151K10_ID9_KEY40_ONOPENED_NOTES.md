# Xenius P151K10: ID9 key40 re-acquire on CameraDevice.onOpened

## User result and rationale
- P151K9 on Vivo X300 Ultra: Additional Lenses → Camera 4 (actual Camera ID9) now shows the **shaky viewfinder**, matching the user's known sign of physical Vivo teleconverter activation. Do not undo the P151K9 active preview-request vendor key.
- However, user reports Vivo key40 does not remain `1`.
- Confirmed stable P151K2 forces `VivoCameraManager.setValue(40,0)` on **every** `Lksn.onClosed` callback, regardless of why the camera closed. An intermediate camera close during lens switching is a plausible cause of OFF before the new ID9 opens; **not proven without P151K9 log**.
- P151K9 calls key40 acquisition in Activity.onResume, `Lkti.a` before `openCamera`, and `Llel.h` after building active requests; ID9 onOpened is an additional precise re-acquire point.

## Patch and scope
- Based on the **K9 unsigned APK**, keeps original K9 3 vendor key paths and its viewfinder behavior.
- ONLY modified `classes.dex`, method `Lksn.onOpened` (DEX method index 43580); no changes to other method bodies or `classes2.dex` gate helper.
- New ID9-only preamble: original `Object.getClass()` check; CameraDevice.getId() equals `"9"`; if true, call `LMC/c2a.getC2apiPref(null)` to request key40 ON using K2's existing idempotent acquisition helper; then `I/RAW50_REPEAT: 9` diagnostic; then original onOpened logic.
- Preserve original onClosed forced-OFF callback (working P151K2 policy) and native 50 MP HDR+ 2–5 frame streams exactly.
- If gate is already ON, acquire helper avoids redundant setValue; if it is 0 and acquisition succeeds, `I/VIVO_GATE: 1` is expected. The log indicates **requested** value, not hardware readback.
- This is a **one-point hypothesis test**, not a solution to a possible late onClosed from a different CameraDevice after the new onOpened event.

## Verification
- DEX opcode boundaries and branch targets including new ID9 preamble, DEX header/checksum, old method bytes preserved, other methods unchanged, archive ZIP integrity and resource alignment all checked offline.
- Signed APK v2 RSA/SHA-256 independently parsed and verified using same developer certificate as P151K2/P151K9; Android runtime install/verification **not available** in environment.

## Phone test
1. Close Xenius; check gate OFF via independent switch. Run `logcat -c` in LADB if possible.
2. Open P151K10, select **Additional Lenses → Camera 4 (ID9)**, confirm shaky TC field of view. Take a 3-frame 50 MP photo.
3. Inspect sequence of `RAW50_REPEAT: 9` (ID9 opened), `VIVO_GATE: 1` (requested ON), `onClosed: onClosed`, `VIVO_GATE: 0` (camera closed), `RAW50_REQ`, `LMC_TC_SESSION`.
4. Exit, confirm gate OFF and stock camera works. **Do not interpret a gate read done AFTER leaving Xenius as evidence that gate failed to turn ON during live preview**—K2 intentionally resets it on camera close.
5. Export:
   `logcat -d -b main,system,crash -v threadtime > /sdcard/Download/P151K10_ID9_KEY40_TEST.txt`
6. If K10 does not restore key40 during ID9 preview, send log and time of switching ID5→ID9. A trace is necessary before modifying onClosed lifecycle logic.

## Artifact files
- XENIUS_P151K10_ID9_ONOPENED_REACQUIRE_V2_SIGNED.apk
- XENIUS_P151K10_ID9_ONOPENED_REACQUIRE_UNSIGNED.apk
- build_p151k10_id9_onopened_key40.py
- sign_xenius_p151k10_v2.py