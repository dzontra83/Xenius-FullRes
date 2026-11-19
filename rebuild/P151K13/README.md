# P151K13 exact DEX reconstruction from working P151K2

This is the **reproducible source-level / binary-delta handoff** for the user-tested
Xenius LMC 8.3 P151K13 build (Vivo X300 Ultra, ID5 + ID9).
It does **not** contain an APK signing private key.

## Input
- `XENIUS_P151K2_FORCE_KEY40_OFF_ONCLOSED_V2_SIGNED.apk`
- Size 84,948,609 bytes; SHA-256
  `385403d5346544046e1911e018a07c4bfd53a17f5b3d6326886b306613371e5d`.
- Python 3 and command-line `git`.

## Build
```bash
python3 build_p151k13_from_k2.py /path/to/XENIUS_P151K2_FORCE_KEY40_OFF_ONCLOSED_V2_SIGNED.apk
```

The script requires that precise K2 APK and applies `git apply --binary` to
`classes.dex` using `K2_TO_K13_CLASSES_DEX.gitpatch`. It checks the result
against exact P151K13 DEX SHA-256
`840d635502613b999ef70d834fcb4096bb75f04020e54d22c2d7d40f2fbbf5d5`.

Output is **UNSIGNED**. Rewriting the APK invalidates its Android APK v2
signature. Use a legitimately controlled Android signing key and `apksigner`
before attempting installation. A different signing certificate normally
requires uninstalling the installed same-package app; backup XML/preferences.

## Verification
On the development computer, this workflow was executed with the actual
K2 APK. The reconstructed 8,225,256-byte `classes.dex` has the exact
P151K13 digest; every ZIP entry has the same uncompressed size and CRC as
the working signed P151K13 APK. This does **not** reproduce the original
APK v2 signing block or make a byte-identical signed APK.

## P151K13 behavior
- `Llel.h` GCam request-builder hook only for physical Camera ID9:
  `vivo.control.extLensInfo=[1,200,2]`.
- Retains K2's ID5 FullRes HDR+ functionality and key40 OFF-on-close logic.
- User-tested: 50MP photo on ID5; physical TC on ID9 and 3-frame 50MP photo;
  key40 returned to 0 on exit.
- Do not include K14/K15 8-frame or F35 experimental patches in this checkpoint.

Original signed APK binary fingerprint:
`ba31d3b48441c8f8ee6b2d1f219af33ddd0916642487f00a4e73f1bf35d84f95`
(84,948,829 bytes). The signed APK itself is **not** included in GitHub.
