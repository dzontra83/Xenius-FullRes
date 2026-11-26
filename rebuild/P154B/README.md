# Xenius P154B — quiet build (no toast, no probe/log files)

**APK:** `XENIUS_P154B_QUIET_UNSIGNED.apk` (unsigned; sign with your K13 key). Built on P153B.
classes.dex SHA-256 `b3482bcab02c1073aae6954db17e3d6888dbf25a52dbd814a1e0949116f0cbca`.

## Why
P153B still had debug side effects from the 50 MP bring-up:
- a **"RAW50_REQ:applied / rejected" toast** above the shutter;
- **`Download/RAW50_C_PROBE1.txt`** (created through MediaStore, appended per burst frame);
- private logs in `Android/data/com.meitu.xenius135a01/files/`: `RAW50_REQ`, `FrameNumber`, `Gcam_GetNumCameras`;
- an **exception fallback in `Lleu.onImageAvailable`** that dumped the whole 8192×6144 frame as a ~100 MB
  `RAW50_REQ*.dng` into the private folder; the "applied" toast was the end of that path.

## Changes (all in-place word replacements: same code length, no branch/try/layout changes)
| | Where | Change |
|---|---|---|
| T | `Lleu.onImageAvailable` | both `Toast.show()` → nop |
| D | `Lleu.onImageAvailable` pc 67 | `if-ne` (buffer == 100663296) → `goto` to the existing "rejected" edge: the fallback DNG dump is never written |
| M | `Lleu.onImageAvailable` | `ContentResolver.insert` of the Download probe file → `null`, so the file is never created and `Ldvm.n/.t` skip (uri == null) |
| W | `Llei` / `Lleu` / `Ldvm` / `Ldux` | every `FileWriter` / `PrintWriter` / `FileOutputStream` construction, `write`, `println`, `close` → nop |

Frame slots, per-frame metadata (System properties), key40, RES 12/50, 25 frames and the ISO cap are unchanged.
The builder checks that no surviving instruction reads a register whose `new-instance` was removed.
Stock GCam caches in `Android/data/.../cache/` (`relightnet_*.cache`, `facelight.cache`) are normal.

## Build
```bash
# copy rebuild/*/build_*.py + tools/dex/*.py into one folder
XENIUS_MAXF=25 python3 build_p153.py XENIUS_P151K13_MINIMAL_ID9_ONLY_V2_SIGNED.apk p153b.apk
python3 build_p154.py p153b.apk XENIUS_P154B_QUIET_UNSIGNED.apk
```
`build_p154.py` asserts the P153B classes.dex hash (`0f76e0be…7e55`). Reproduced byte-exact from K13.

## After installing
Delete leftovers once: `Download/RAW50_C_PROBE1*.txt` and everything in `Android/data/com.meitu.xenius135a01/files/`.
Then shoot 12 MP and 50 MP: no toast, and `files/` stays empty.

## Related research (branch `p31-stream-lab`)
Stream Lab P31–P34 (standalone Camera2 probe) on ID 5: full-view 50/200 MP is always hardware-remosaiced;
`EngineerRemosaicMode`, XCFA, `seamless.remosaic.enable` and NR/edge off are accepted but don't change the RAW.
`forceSensorMode` 5/10/13/17 give 12 MP quad (2×2) and 7 gives 12 MP 4×4 (in-sensor crops); 1 and 27 are accepted
but deliver no frames at 8192/8160×6144 or 200 MP; 1, 3, 4, 14, 18, 24–28 crash the HAL on a 12 MP stream.
