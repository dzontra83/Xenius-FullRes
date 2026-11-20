#!/usr/bin/env python3
"""XENIUS P160 — focus lock off, OIS copy kept, on top of P159 (classes2.dex unchanged).

P158B locked focus for the 50 MP burst (AF OFF + the preview result's LENS_FOCUS_DISTANCE). On vivo the reported
focus distance is not a usable lens position (user: 50 MP blurry), so the lens could be parked at the wrong distance.
P160: the burst-build step (L2) looks the stored focus distance up under a key that is never set ('LENS_FOCUS_RANGE'),
so AF mode / focus distance stay as the STILL_CAPTURE template has them (pre-P158B behaviour). OIS mode copy unchanged.
One string index changed in place.

Run: python3 build_p160.py XENIUS_P159_12MPFIX_UNSIGNED.apk XENIUS_P160_NOAFLOCK_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr

P159_DEX = '5f24d4d4ca2a9e960d9777f359c2359992c0b1107bada94c2d97ae3399e099c5'

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P159_DEX, 'classes.dex is not P159'
    open('/tmp/_p160.dex', 'wb').write(raw); d = Dex('/tmp/_p160.dex')
    get = mid(d, 'Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    kfd, never = sid(d, 'LENS_FOCUS_DISTANCE'), sid(d, 'LENS_FOCUS_RANGE')
    assert not d.xrefs_string(never), 'LENS_FOCUS_RANGE is used somewhere'
    m = one(d, 'Llei;', 'onCaptureCompleted'); (_, _, _, _), w = d.insns(m); w = list(w)
    hits = [i for i in range(len(w) - 4) if w[i:i + 5] == [0x011a, kfd, 0x2072, get, 0x0010]]
    assert len(hits) == 1, hits
    b = bytearray(raw); struct.pack_into('<H', b, d.code[m] + 16 + 2 * (hits[0] + 1), never); fix_hdr(b)
    return bytes(b)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
