#!/usr/bin/env python3
"""XENIUS P168 — EXIF FocalLength = 35 mm-equivalent (so Google Photos shows 14 / 35 / 85 mm, not 11.56 mm).

At JPEG write (Llpy.j, after the P163D Model line, before `if-nez v4`), with v0..v2 free:
    eq = exif.b(ExifInterface.aB)                    # FocalLengthIn35mmFilm (0xA405), written by GCam per lens
    if eq > 0: exif.y(exif.i(ExifInterface.Z, Lkvj.h(Float(eq), Long(1))))   # FocalLength (0x920A) = eq/1
FocalLengthIn35mmFilm itself is unchanged. Applies to 12 MP and 50 MP, every lens.
Base: P167 (classes.dex 9ec4515c...f81b). Run: python3 build_p168.py XENIUS_P167_UNSIGNED.apk XENIUS_P168_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S

P167_DEX = '9ec4515c489c6a4821cbdb67a3029ac64a7498e8503c99b353c091f623d5f81b'
EI = 'Lcom/google/android/libraries/camera/exif/ExifInterface;'


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P167_DEX, 'classes.dex is not P167'
    open('/tmp/_p168.dex', 'wb').write(raw); d = Dex('/tmp/_p168.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    F = lambda n: [i for i, f in enumerate(d.fields) if f == (EI, 'I', n)][0]
    eb = M(EI, 'b', '(I)Ljava/lang/Integer;'); ei = M(EI, 'i', '(ILjava/lang/Object;)Lkvh;'); ey = M(EI, 'y', '(Lkvh;)V')
    iv = M('Ljava/lang/Integer;', 'intValue', '()I')
    fvo = M('Ljava/lang/Float;', 'valueOf', '(F)Ljava/lang/Float;'); lvo = M('Ljava/lang/Long;', 'valueOf', '(J)Ljava/lang/Long;')
    rat = M('Lkvj;', 'h', '(Ljava/lang/Float;Ljava/lang/Long;)Lkrb;')
    FZ, F35 = F('Z'), F('aB')
    m = [i for i, (c, p, n) in enumerate(d.methods) if c == 'Llpy;' and n == 'j' and i in d.code and EI in d.mname(i)]
    assert len(m) == 1; m = m[0]
    c = Code(raw, d.code[m])
    # anchor: the P163D Model block ends with  invoke-virtual {v4,v0} y ; then nop ; if-nez v4
    hits = [i for i in range(len(c.w) - 6) if c.w[i:i + 3] == [0x206e, ey, 0x0004] and c.w[i + 3] == 0 and c.w[i + 4] & 0xff == 0x39]
    assert len(hits) == 1, hits
    p = hits[0] + 4
    def B(base, na):
        a = S(base)
        a.b21(0x38, 4, 'end')
        a.raw(0x0060, F35); a.inv(0x6e, eb, [4, 0]); a.mro(0); a.b21(0x38, 0, 'end')
        a.inv(0x6e, iv, [0]); a.mr(0); a.b21(0x3d, 0, 'end')
        a.raw(0x0082 | 0 << 8 | 0 << 12)                   # int-to-float v0, v0
        a.inv(0x71, fvo, [0]); a.mro(0)
        a.raw(0x0116, 1)                                   # const-wide/16 v1, 1
        a.inv(0x71, lvo, [1, 2]); a.mro(1)
        a.inv(0x71, rat, [0, 1]); a.mro(0); a.b21(0x38, 0, 'end')
        a.raw(0x0160, FZ); a.inv(0x6e, ei, [4, 1, 0]); a.mro(0); a.b21(0x38, 0, 'end')
        a.inv(0x6e, ey, [4, 0])
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
