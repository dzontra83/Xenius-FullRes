#!/usr/bin/env python3
"""XENIUS P163D — HDR+ frame count in the EXIF Model, set when the JPEG file is written. On top of P162B.

P163C showed: the EXIF bytes are built (Ldub.a) before HDR+ reports its merge stats (Lohy.accept), on 12 and 50 MP.
But the EXIF is serialised from the ExifInterface object only when the file is written (Llpy.j -> ExifInterface.m).
 E2 Lohy.accept pc 366: props["ShotLogData_original_payload_frame_count_get"] = "<merged>/<original>".
 E4 Llpy.j entry (JPEG bytes + ExifInterface -> file): if exif != null and a value is stored (taken = removed):
    exif.setTag(exif.buildTag(TAG_MODEL=0x0110, Build.MODEL + " " + value + " frames")).
No placeholder in StaticMetadata anymore (DNG keeps the plain model). No value at save time -> plain model.

Run: python3 build_p163d.py XENIUS_P162B_GYRO_UNSIGNED.apk XENIUS_P163D_EXIFCOUNT_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S, P162B_DEX

EXIF = 'Lcom/google/android/libraries/camera/exif/ExifInterface;'


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P162B_DEX, 'classes.dex is not P162B'
    open('/tmp/_p163d.dex', 'wb').write(raw); d = Dex('/tmp/_p163d.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    STR = 'Ljava/lang/String;'
    cat = M(STR, 'concat', '(Ljava/lang/String;)Ljava/lang/String;')
    vi = M(STR, 'valueOf', '(I)Ljava/lang/String;')
    props = M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    put = M('Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    rem = M('Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;')
    build = M(EXIF, 'i', '(ILjava/lang/Object;)Lkvh;')
    settag = M(EXIF, 'y', '(Lkvh;)V')
    SP, SL, FR, PHS = sid(d, ' '), sid(d, '/'), sid(d, ' frames'), sid(d, 'RAW50_REQ')
    KVAL = sid(d, 'ShotLogData_original_payload_frame_count_get')
    fmodel = [i for i, f in enumerate(d.fields) if f == ('Landroid/os/Build;', STR, 'MODEL')][0]
    out = {}

    m = one(d, 'Lohy;', 'accept'); c = Code(raw, d.code[m])
    assert c.w[366:368] == [0x041a, PHS]
    nzk = lambda n: [i for i, f in enumerate(d.fields) if f == ('Lnzk;', 'I', n)][0]
    def E2(p, na):   # v3 = Lnzk; v0,v4,v5,v6 free
        a = S(p)
        a.raw(0x0052 | 4 << 8 | 3 << 12, nzk('o')); a.inv(0x71, vi, [4]); a.mro(4)
        a.cs(6, SL); a.inv(0x6e, cat, [4, 6]); a.mro(4)
        a.raw(0x0052 | 5 << 8 | 3 << 12, nzk('m')); a.inv(0x71, vi, [5]); a.mro(5)
        a.inv(0x6e, cat, [4, 5]); a.mro(4)
        a.inv(0x71, props, []); a.mro(0); a.cs(6, KVAL); a.inv(0x72, put, [0, 6, 4])
        return a.done()
    insert(c, 366, E2); check(c); out[m] = c.build()

    m = one(d, 'Llpy;', 'j'); c = Code(raw, d.code[m])
    assert c.regs == 6 and c.ins == 3 and c.w[0] == 0x0439 and all(t[0] > 0 for t in c.tries)   # if-nez v4
    def E4(p, na):   # v3 jpeg, v4 exif, v5 llkb; v0..v2 free
        a = S(p)
        a.b21(0x38, 4, 'skip')
        a.inv(0x71, props, []); a.mro(0); a.cs(1, KVAL); a.inv(0x72, rem, [0, 1]); a.mro(0)
        a.b21(0x38, 0, 'skip'); a.raw(0x001f, d.types.index(STR))
        a.raw(0x0162, fmodel); a.cs(2, SP); a.inv(0x6e, cat, [1, 2]); a.mro(1)
        a.inv(0x6e, cat, [1, 0]); a.mro(1); a.cs(2, FR); a.inv(0x6e, cat, [1, 2]); a.mro(1)
        a.c16(0, 0x0110); a.inv(0x6e, build, [4, 0, 1]); a.mro(0)
        a.b21(0x38, 0, 'skip'); a.inv(0x6e, settag, [4, 0])
        a.L('skip')
        return a.done()
    insert(c, 0, E4); check(c); out[m] = c.build()

    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
