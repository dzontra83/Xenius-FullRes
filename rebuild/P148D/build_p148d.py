#!/usr/bin/env python3
"""XENIUS P148D — P148C + key40 never released on camera close while RES ON.

P148B/C log: CameraActivity.onResume never ran (no 'RESOLUTION_SWITCH: onResume'), so the foreground mark was
never set and Lksn.onClosed kept releasing key40 after a new camera had acquired it. RawR: releasing after the
full-size session is configured breaks full-size stills.
  D1 Lksn.onClosed: RES ON -> never release (mark check removed). Release only at CameraActivity.onStop (K3).
  D2 Larb.handleMessage: acquire key40 right before its openCamera (Lkti.a already does).
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, walk
from build_p149a import Asm, one, mid, sid, rebuild_apk
import build_p149b as B, build_p148a as A, build_p148b as K, build_p148c as C


def d_methods(d, new):
    gate = mid(d, 'LMC/c2a;', 'getC2apiPref', '(Lleo;)Lleo;')
    getm = mid(d, 'Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    # D1
    c = new[one(d, 'Lksn;', 'onClosed')]
    seq = [pc for pc, ln, pay in walk(c.w) if not pay]
    hits = [pc for i, pc in enumerate(seq[:-2]) if (c.w[pc] & 0xff) == 0x72 and c.w[pc + 1] == getm
            and c.w[seq[i + 1]] == 0x000c and c.w[seq[i + 2]] == 0x0038]
    assert len(hits) == 1, hits
    p = [q for q in seq if q > hits[0]][1]            # the if-eqz v0 (mark absent -> release)
    c.w[p] = 0; c.w[p + 1] = 0; check(c)
    # D2
    m = one(d, 'Larb;', 'handleMessage'); c = Code(d.b, d.code[m])
    assert c.w[686] == 0xc254 and c.w[692] & 0xff == 0x6e
    def D2(p, na):
        a = Asm(p); a.w += [0x0212]; a.inv_static(gate, [2]); return a.done()   # const/4 v2,0 ; getC2apiPref(null)
    insert(c, 686, D2); check(c); new[m] = c


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.extra_methods(d, new); K.key40_methods(d, new); C.metadata_guards(d, new); d_methods(d, new)
    c1 = B.finalize_classes(raw1, d, new); c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p148d', 'wb').write(c1)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
