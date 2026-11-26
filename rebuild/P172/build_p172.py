#!/usr/bin/env python3
"""XENIUS P172 — P165 + P167 (burst-length cap) + P168 (35 mm-eq focal length), WITHOUT P166 (HDR++ exposure link).
The 50 MP burst again copies the viewfinder ISO/exposure (Auto rule: ISO > 2400 -> 2400, max 125 ms).
Run: python3 build_p172.py XENIUS_P165_UW50_UNSIGNED.apk XENIUS_P172_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_p167 as A, build_p168 as B
from build_p149a import rebuild_apk
P165_DEX = 'a99b82034b00949b8fe4464473e80c307a0af4fa88efdf76afb2cb0c36973240'

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P165_DEX, 'classes.dex is not P165'
    A.P166_DEX = P165_DEX; x = A.patch(raw)
    B.P167_DEX = hashlib.sha256(x).hexdigest(); return B.patch(x)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
