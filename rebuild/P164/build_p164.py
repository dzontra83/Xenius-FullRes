#!/usr/bin/env python3
"""XENIUS P164 — P156 base (25-frame cap, original HDR+ hand-off) + the keepers from P158B..P163E, without P157.

P156L log: 5 bursts, every captured 50 MP frame reached HDR+ (contiguous frame numbers, merged = handed over: 20, 18,
14, 13, 19). The P157-based line lost frames mid-burst (P163L: frame numbers 89/96/98 captured but never handed over).
P157's streaming hand-off gave no speed gain (GCam's own payload frame arrives only after the burst, then all frames
are fed within ~40 ms), so P164 drops P157 (and P159, which only fixed P157's 12 MP wait).
Chain on the P156 classes.dex: P158B (OIS + focus lock) -> P160 (focus lock off) -> P162 (normal-listener gyro)
-> P162B (gyro gate open) -> P163D (frame count in EXIF Model at save) -> P163E (save waits for the stats).
Run: python3 build_p164.py XENIUS_P156_FLUSH_UNSIGNED.apk XENIUS_P164_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_p158 as B158, build_p160 as B160, build_p162 as B162, build_p162b as B162B, build_p163d as D, build_p163e as E
from build_p149a import rebuild_apk

h = lambda b: hashlib.sha256(b).hexdigest()
P156_DEX = 'b4c951943d952f47f47b9c1a25c7713f71590a2fdb961067625c18e50020ec35'

def patch(raw):
    assert h(raw) == P156_DEX, 'classes.dex is not P156'
    B158.P157_DEX = h(raw); raw = B158.patch(raw)
    B160.P159_DEX = h(raw); raw = B160.patch(raw)
    B162.BASES = {h(raw): 'P156+OIS'}; raw = B162.patch(raw)
    B162B.BASES = {h(raw): 'P156+OIS+gyro'}; raw = B162B.patch(raw)
    D.P162B_DEX = h(raw); raw = D.patch(raw)
    E.P163D_DEX = h(raw); raw = E.patch(raw)
    return raw

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', h(new)); print('wrote', dst)
