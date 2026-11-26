# Xenius LMC 8.3 FullRes development — checkpoint P151K13

**Updated:** 2026-11-19. **Last known-good user-tested release:** P151K13.  
**Project:** Vivo X300 Ultra, LMC 8.3 / Xenius GCam. **Camera IDs:** ID5 native 85mm; ID9 physical 200mm teleconverter.

## Scope and provenance
This sync preserves the repository's previous P25–P31 work and adds historical development notes between 2026-11-15 and P151K13. No build later than **P151K13** is included in the checkpoint. Archives after this checkpoint, including K14/K15 and F35 B-series, are excluded by design.

## User-confirmed K13 behavior (19 November 2026)
- Built from P151K2, which restores camera vendor key40 to OFF on camera close.
- `Llel.h()` injects `vivo.control.extLensInfo = [1,200,2]` **only for physical Camera ID9** in GCam's request builder. Guarded by `CameraDevice.getId().equals("9")`.
- ID5 FullRes 50 MP capture works.
- ID9 teleconverter request enables the expected TC viewfinder behavior and saved a **3-frame** 50 MP image in the user's test.
- Key40 returned to 0 after closing the app (user checked).
- No more aggressive K6–K12 session, still-request, preview or global key40 acquisition patches.
- **Do not claim >3-frame ID9 HDR+ capture was validated at K13.** K13 is the validated fallback, not the 8-frame or 200MP experiments.

## Exact binary checkpoint
- Signed APK name: `XENIUS_P151K13_MINIMAL_ID9_ONLY_V2_SIGNED.apk`.
- Android package: `com.meitu.xenius135a01` (same as the K2 branch).
- APK file length: **84,948,829 bytes**.
- SHA-256: `ba31d3b48441c8f8ee6b2d1f219af33ddd0916642487f00a4e73f1bf35d84f95`.
- Predecessor: `XENIUS_P151K2_FORCE_KEY40_OFF_ONCLOSED_V2_SIGNED.apk`, 84,948,609 bytes, SHA-256 `385403d5346544046e1911e018a07c4bfd53a17f5b3d6326886b306613371e5d`.
- Offline comparison of the two APK ZIPs found exactly **one changed APK entry: `classes.dex`** (different uncompressed length); all other ZIP entries have identical file size and CRC. This checkpoint records binary provenance, not source-code-level reproducibility.

## Technical history
1. P32–P67: RAW / native pointer / FullRes reader contract investigations.
2. P68–P83: 50 MP sensor buffer and DNG acquisition, listener and save-path experiments.
3. P84–P103: RawWriteView, Camera2 metadata, native geometry and key40 restoration.
4. P104–P113: native shot lifecycle, valid shot ID 0, RAW callback and ImageReader cleanup. P112 repaired repeated 50 MP DNG capture by closing images and native views.
5. P114–P135: native frame metadata, HDR+ payload entry and BurstSpec/ZSL investigation. Partial native callbacks and diagnostics do not prove HDR+ merge.
6. P151 series: resolution gate, 50 MP 2/3/5-frame HDR+ experiments, key40 lifecycle and ID9 GCam request activation.
7. P151K13: narrow production-style stable checkpoint above.

## Safety and exclusions
- Preserve original Black/White levels and existing DCG configurations; FullRes does **not** use DCG.
- Keep original ID5 and ID9 camera settings and XML unaffected by this documentation sync.
- Keep original P151K13 APK as an immutable reference (do not overwrite its binary).
- No signing private keys, user/device logs, DNG photographs, configuration dumps or post-K13 experimental APKs in this checkpoint.
- The source ZIP archives are now backed up as six binary bundles under `source-archives/through-P151K13/`; see `SOURCE_BUNDLE_INDEX.md`. The signed 84.95 MB APK remains external to GitHub, with hash and size recorded here.

## Source material
Historical technical notes were copied from files generated across the relevant Xenius development sessions, under `history/through-P151K13/notes/`, retaining original filenames. Earlier GitHub P25–P31 source archives and workflows stay untouched.
