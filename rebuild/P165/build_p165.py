#!/usr/bin/env python3
"""XENIUS P165 — UW (ID4) 50 MP: arm the burst for a 4096-wide GCam RAW reader too.

Lkyu.get stores GCam's 12 MP RAW ImageReader as props['rejected'] only when width == 4080 (ID3/ID5).
The UW (ID4) RAW is 4096x3072, so the reader was never stored, the shutter hook never armed the
50 MP burst and HDR+ waited forever (no picture). Insert before the if-nez at pc 1002:
    add-int/lit8 v32, v31, -16 ; if-nez v32, +4 ; const/16 v31, 0      (width-4080 == 16 -> treat as 4080)
Bases: P164B (default) or P165L (log build).
Run: python3 build_p165.py IN.apk OUT.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, rebuild_apk
from build_p149b import fix_hdr

BASES = {'dd43b3d2d9c90fb002a631eb95732c31b6cae22f41748d58ef079b10d6a22ea5': 'P164B',
         '14e4f1e5d4306da899d3fd21ffdec7f2f492da4c747ac635c547a0cc083227b7': 'P165L'}


def patch(raw):
    h = hashlib.sha256(raw).hexdigest(); assert h in BASES, h
    open('/tmp/_p165.dex', 'wb').write(raw); d = Dex('/tmp/_p165.dex')
    m = one(d, 'Lkyu;', 'get'); c = Code(raw, d.code[m])
    # locate: const/16 v32,4080 is 'const/16' with 8-bit reg 32 -> word 0x2013, 0x0ff0
    hits = [i for i in range(len(c.w) - 6) if c.w[i] == 0x2013 and c.w[i + 1] == 4080]
    assert len(hits) == 1, hits
    q = hits[0]
    assert c.w[q + 2] & 0xff == 0x91 and (c.w[q + 2] >> 8) == 31         # sub-int v31, v31, v32
    assert c.w[q + 4] & 0xff == 0x39 and (c.w[q + 4] >> 8) == 31         # if-nez v31
    p = q + 4
    def B(pp, na):
        return [0x20d8, 0xf01f,          # add-int/lit8 v32, v31, -16
                0x2039, 4,               # if-nez v32, +4 (skip const)
                0x1f13, 0x0000]          # const/16 v31, 0
    insert(c, p, B); check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o), BASES[h]


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new, base = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print(base, '-> classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
