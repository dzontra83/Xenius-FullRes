#!/usr/bin/env python3
"""XENIUS P169T — TEST: 50 MP burst exposure x0.707 (-0.5 EV), ISO unchanged.
Question it answers: does the 50 MP output brightness follow the burst exposure (then this is the fix for
'50 MP too bright'), or does HDR+ normalise it from the frame metadata (then output looks the same)?
Inserted just before P167's store of the burst-length value (so the cap uses the scaled exposure).
Base: P168 (classes.dex 07948dae...). Run: python3 build_p169t.py XENIUS_P168_UNSIGNED.apk XENIUS_P169T_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S
P168_DEX = '07948daef5a9e65c1e90def7d694a074590b5381324fec8ecf1bf0fe61c3d76d'
FACTOR = float(os.environ.get('XENIUS_EXPO', '0.7071'))
fb = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P168_DEX
    open('/tmp/_p169.dex', 'wb').write(raw); d = Dex('/tmp/_p169.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    lv = M('Ljava/lang/Long;', 'longValue', '()J'); lvo = M('Ljava/lang/Long;', 'valueOf', '(J)Ljava/lang/Long;')
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])
    K = sid(d, 'SENSOR_EXPOSURE_TIME')
    h = [i for i in range(len(c.w) - 3) if c.w[i:i + 2] == [0x011a, K] and c.w[i + 2] == 0x0238]
    assert len(h) == 1, h
    p = h[0]
    def B(base, na):
        a = S(base)
        a.b21(0x38, 2, 'end')
        a.raw(0x001f | 2 << 8, d.types.index('Ljava/lang/Long;'))
        a.inv(0x6e, lv, [2]); a.raw(0x000b | 6 << 8)
        a.raw(0x0085 | 4 << 8 | 6 << 12)
        a.c32(6, fb(FACTOR)); a.raw(0x00a8 | 4 << 8, 4 | 6 << 8)
        a.raw(0x0088 | 6 << 8 | 4 << 12)
        a.inv(0x71, lvo, [6, 7]); a.mro(2)
        a.L('end')
        return a.done()
    insert(c, p, B); check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
