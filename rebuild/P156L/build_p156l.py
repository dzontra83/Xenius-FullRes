#!/usr/bin/env python3
"""XENIUS P156L — P156 (25-frame cap, no P157+ changes) + EXIF frame count (P163D/E) + merge.txt log (P163L).

Chain on the P156 classes.dex: P163D (Lohy stats -> Model at save) -> P163L (Download/merge.txt: frame / exif /
merge lines) -> P163E (save waits for the stats). classes2.dex = P155.
Run: python3 build_p156l.py XENIUS_P156_FLUSH_UNSIGNED.apk XENIUS_P156L_25F_LOG_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_p163d as D, build_p163l as L, build_p163e as E
from build_p149a import rebuild_apk

h = lambda b: hashlib.sha256(b).hexdigest()
P156_DEX = 'b4c951943d952f47f47b9c1a25c7713f71590a2fdb961067625c18e50020ec35'

def patch(raw):
    assert h(raw) == P156_DEX, 'classes.dex is not P156'
    D.P162B_DEX = h(raw); raw = D.patch(raw)
    L.P163D_DEX = h(raw); raw = L.patch(raw)
    E.P163D_DEX = h(raw); raw = E.patch(raw)
    return raw

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', h(new)); print('wrote', dst)
