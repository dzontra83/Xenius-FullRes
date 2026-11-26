#!/usr/bin/env python3
"""Rebuild P151K13's exact classes.dex from the P151K2 APK.

WARNING: This emits an UNSIGNED APK. Android APK v2/v3 signatures from
P151K2 do not survive rewriting the ZIP. Sign externally with apksigner.
No signing secret or key is stored by this script.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import zipfile

K2_SHA256 = '385403d5346544046e1911e018a07c4bfd53a17f5b3d6326886b306613371e5d'
K13_DEX_SHA256 = '840d635502613b999ef70d834fcb4096bb75f04020e54d22c2d7d40f2fbbf5d5'


def sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def build(base_apk, patch, output):
    if not base_apk.is_file() or not patch.is_file():
        raise SystemExit('Missing K2 APK or K13 binary patch')
    if sha256(base_apk.read_bytes()) != K2_SHA256:
        raise SystemExit('Refusing unexpected base APK: P151K2 SHA-256 mismatch')
    if output.resolve() == base_apk.resolve():
        raise SystemExit('Refusing to overwrite the original K2 APK')
    if output.exists():
        raise SystemExit('Output exists; specify a new filename')
    with tempfile.TemporaryDirectory(prefix='xenius_k13_') as td:
        tmp = Path(td)
        with zipfile.ZipFile(base_apk, 'r') as src:
            original_dex = src.read('classes.dex')
        (tmp/'classes.dex').write_bytes(original_dex)
        subprocess.run(['git', 'apply', '--binary', str(patch.resolve())], cwd=tmp, check=True)
        new_dex = (tmp/'classes.dex').read_bytes()
        if sha256(new_dex) != K13_DEX_SHA256:
            raise SystemExit('Dex patch mismatch: do not build this APK')
        # Writing ZIP entries deliberately drops old APK signing blocks.
        with zipfile.ZipFile(base_apk, 'r') as src, zipfile.ZipFile(output, 'w', allowZip64=True) as dst:
            for info in src.infolist():
                data = new_dex if info.filename == 'classes.dex' else src.read(info.filename)
                dst.writestr(info, data)
            dst.comment = src.comment
    with zipfile.ZipFile(output, 'r') as apk:
        err = apk.testzip()
        if err:
            raise SystemExit('ZIP CRC verification failed: ' + err)
        if sha256(apk.read('classes.dex')) != K13_DEX_SHA256:
            raise SystemExit('Output DEX verification failed')
    print('Built and ZIP-verified:', output)
    print('Exact K13 classes.dex SHA-256:', K13_DEX_SHA256)
    print('NOT INSTALLABLE YET: APK v2 signature is absent; sign externally using Android apksigner.')


if __name__ == '__main__':
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('k2_apk', type=Path)
    a.add_argument('--patch', type=Path, default=Path(__file__).with_name('K2_TO_K13_CLASSES_DEX.gitpatch'))
    a.add_argument('--out', type=Path, default=Path('XENIUS_P151K13_REBUILT_UNSIGNED.apk'))
    ns = a.parse_args()
    build(ns.k2_apk, ns.patch, ns.out)
