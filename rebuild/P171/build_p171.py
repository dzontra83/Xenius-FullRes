#!/usr/bin/env python3
"""XENIUS P171 — 50 MP mode: HDR+ exposure compensation offset (default -0.7 EV) for the shot only.

P169 (real burst exposure lower) and P170 (frame metadata exposure higher) did not change 50 MP output brightness:
HDR+ renders to its own AE target. So the offset is put into that target: in Ldvm.G (ShotParams builder), before
Ldvm.F(ev, ...) builds AeShotParams, ev += OFFSET when LMC pref 'pref_upscale_key' != 0 (RES / 50 MP on).
12 MP and the viewfinder AE (Ldvm.c -> Ldvm.F) are untouched. XENIUS_EV=<offset> overrides.
Base: P168. Run: python3 build_p171.py XENIUS_P168_UNSIGNED.apk XENIUS_P171_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S
P168_DEX = '07948daef5a9e65c1e90def7d694a074590b5381324fec8ecf1bf0fe61c3d76d'
EV = float(os.environ.get('XENIUS_EV', '-0.7'))
fb = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P168_DEX, 'classes.dex is not P168'
    open('/tmp/_p171.dex', 'wb').write(raw); d = Dex('/tmp/_p171.dex')
    Fm = mid(d, 'Ldvm;', 'F', '(FLdwf;)Lcom/google/googlex/gcam/AeShotParams;')
    mv = mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    m = one(d, 'Ldvm;', 'G'); c = Code(raw, d.code[m])
    hits = [i for i in range(len(c.w) - 3) if c.w[i] == 0x3070 and c.w[i + 1] == Fm]
    assert len(hits) == 1, hits
    p = hits[0]
    assert c.w[p + 2] == (15 | 5 << 4 | 4 << 8), hex(c.w[p + 2])      # {v15, v5, v4}
    def B(base, na):
        a = S(base)
        a.cs(6, sid(d, 'pref_upscale_key')); a.inv(0x71, mv, [6]); a.mr(6)
        a.b21(0x38, 6, 'end')
        a.c32(6, fb(EV)); a.raw(0x00c6 | 5 << 8 | 6 << 12)          # add-float/2addr v5, v6
        a.L('end')
        return a.done()
    insert(c, p, B); check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('EV', EV, 'classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
