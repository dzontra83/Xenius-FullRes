#!/usr/bin/env python3
"""XENIUS P163E — frame count in EXIF every time: the JPEG save waits for the HDR+ merge stats. On top of P163D.

P163L log: per shot, "exif" (EXIF built) comes ~0.4-0.5 s before "merge" (HDR+ stats), and the file save races
the stats -> the count appears on some photos only.
 W1 Ldub.a pc 53 (EXIF built for a GCam shot): props["ShotLogData_merge_process_time_get"] = pending flag.
 W2 Llpy.j entry (before P163D's model code): if the pending flag is set (taken), wait up to 3 s (20 ms steps)
    for the stats value to appear, then continue -> P163D sets the Model. No flag -> no wait.

Run: python3 build_p163e.py XENIUS_P163D_EXIFCOUNT_UNSIGNED.apk XENIUS_P163E_EXIFCOUNT_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S
from build_p163l import P163D_DEX


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P163D_DEX, 'classes.dex is not P163D'
    open('/tmp/_p163e.dex', 'wb').write(raw); d = Dex('/tmp/_p163e.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    props = M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    get = M('Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    put = M('Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    rem = M('Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;')
    sleep = M('Landroid/os/SystemClock;', 'sleep', '(J)V')
    KPEND = sid(d, 'ShotLogData_merge_process_time_get')
    KVAL = sid(d, 'ShotLogData_original_payload_frame_count_get')
    out = {}

    m = [i for i, (cc, pp, nn) in enumerate(d.methods) if cc == 'Ldub;' and nn == 'a' and 'ShotMetadata' in d.mname(i)][0]
    c = Code(raw, d.code[m])
    tE = d.types.index('Lcom/google/android/libraries/camera/exif/ExifInterface;')
    pos = [i for i in range(len(c.w) - 1) if c.w[i:i + 2] == [0x0722, tE]]
    assert len(pos) == 1, pos
    P53 = pos[0]
    def W1(p, na):   # v0, v2 free
        a = S(p); a.inv(0x71, props, []); a.mro(0); a.cs(2, KPEND); a.inv(0x72, put, [0, 2, 2])
        return a.done()
    insert(c, P53, W1); check(c); out[m] = c.build()

    m = one(d, 'Llpy;', 'j'); c = Code(raw, d.code[m])
    assert c.w[0] == 0x0438 and c.w[2:4] == [0x0071, props]                 # P163D E4: if-eqz v4 ; getProperties
    def W2(p, na):   # v0..v2 free
        a = S(p)
        a.inv(0x71, props, []); a.mro(1); a.cs(2, KPEND); a.inv(0x72, rem, [1, 2]); a.mro(1)
        a.b21(0x38, 1, 'go')
        a.c16(0, 150)
        a.L('loop'); a.inv(0x71, props, []); a.mro(1); a.cs(2, KVAL); a.inv(0x72, get, [1, 2]); a.mro(1)
        a.b21(0x39, 1, 'go')
        a.raw(0x0116, 20); a.inv(0x71, sleep, [1, 2])                         # const-wide/16 v1, 20 ; sleep
        a.lit8(0xd8, 0, 0, -1); a.b21(0x3c, 0, 'loop')
        a.L('go')
        return a.done()
    insert(c, 0, W2); check(c); out[m] = c.build()

    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
