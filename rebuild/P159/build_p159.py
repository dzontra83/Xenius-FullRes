#!/usr/bin/env python3
"""XENIUS P159 — fix P157's 12 MP slowdown, on top of P158B (classes2.dex unchanged).

P157 added per-frame waits (up to 3 s) in Ldvm.p for slot 2 and slots 3..N. Ldvm.p also runs after every normal
12 MP payload frame, where no 50 MP frame ever arrives, so each 12 MP frame waited the full 3 s timeout.
Fix: each wait only runs while a 50 MP burst is active, i.e. the slot-1 marker 'new_RawWriteView__SWIG_1' is set
(set by the first 50 MP frame, kept by the feeder since P157, cleared at the next burst start; never set in 12 MP).
No marker -> skip the wait (old behaviour).

Run: python3 build_p159.py XENIUS_P158B_STEADY_UNSIGNED.apk XENIUS_P159_12MPFIX_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr

P158B_DEX = '94e8d3be5541fa8eed1f14958eec28afabb72572423f972edd8fe82cd19ec50b'


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P158B_DEX, 'classes.dex is not P158B'
    open('/tmp/_p159.dex', 'wb').write(raw); d = Dex('/tmp/_p159.dex')
    get = mid(d, 'Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    marker = sid(d, 'new_RawWriteView__SWIG_1')
    m = one(d, 'Ldvm;', 'p'); c = Code(raw, d.code[m])
    hits = [i for i in range(len(c.w) - 4) if c.w[i:i + 5] == [0x0413, 300, 0x2072, get, 0x0010]]
    assert len(hits) == 2, hits
    for p in sorted(hits, reverse=True):
        out = [i for i in range(p, p + 30) if c.w[i] == 0x043c][0] + 2       # after if-gtz v4, loop
        def blk(base, na, out=out):
            w = [0x021a, marker, 0x2072, get, 0x0020, 0x020c]                 # const-string v2 ; get {v0,v2} ; move-result-object v2
            src = base + len(w)
            return w + [0x0238, (na(out) - src) & 0xffff]                     # if-eqz v2, out
        insert(c, p, blk)
    check(c)
    out = bytearray(relocate(raw, {m: c.build()})); fix_hdr(out)
    return bytes(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
