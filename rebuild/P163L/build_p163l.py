#!/usr/bin/env python3
"""XENIUS P163L — P163D + HDR+ timeline log file Download/merge.txt (diagnostic build, no ADB needed).

One line per event, "<epoch ms> <event> <detail>", each write inside a catch-all try (errors are skipped):
  frame  Ldvm.C entry: a frame handed to HDR+ (with its TotalCaptureResult FrameNumber + SENSOR_TIMESTAMP)
  exif   Ldub.a: EXIF block built for the output JPEG
  merge  Lohy.accept: HDR+ merge summary (frames handed over / merged / merge time / SNR / aborted)
(save time is not logged: Llpy.j has only 3 free registers; the gallery Model line shows whether the count was applied)

Run: python3 build_p163l.py XENIUS_P163D_EXIFCOUNT_UNSIGNED.apk XENIUS_P163L_LOG_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S

P163D_DEX = 'bf8fa7a5f77f7c4abe142df3f147205f221d3a53ac5ea92313e2b916d410f2f7'
CR = 'Landroid/hardware/camera2/CaptureResult;'


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P163D_DEX, 'classes.dex is not P163D'
    open('/tmp/_p163l.dex', 'wb').write(raw); d = Dex('/tmp/_p163l.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    STR = 'Ljava/lang/String;'
    I = dict(
        cat=M(STR, 'concat', '(Ljava/lang/String;)Ljava/lang/String;'),
        vo=M(STR, 'valueOf', '(Ljava/lang/Object;)Ljava/lang/String;'),
        vj=M(STR, 'valueOf', '(J)Ljava/lang/String;'),
        sub=M(STR, 'substring', '(II)Ljava/lang/String;'),
        now=M('Ljava/lang/System;', 'currentTimeMillis', '()J'),
        props=M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;'),
        get=M('Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;'),
        pub=M('Landroid/os/Environment;', 'getExternalStoragePublicDirectory', '(Ljava/lang/String;)Ljava/io/File;'),
        finit=M('Ljava/io/File;', '<init>', '(Ljava/io/File;Ljava/lang/String;)V'),
        fwinit=M('Ljava/io/FileWriter;', '<init>', '(Ljava/io/File;Z)V'),
        wr=M('Ljava/io/Writer;', 'write', '(Ljava/lang/String;)V'),
        cl=M('Ljava/io/Writer;', 'close', '()V'),
        ld=M('Lljm;', 'd', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;'))
    s = lambda x: sid(d, x)
    T = lambda t: d.types.index(t)
    fts = [i for i, f in enumerate(d.fields) if f == (CR, 'Landroid/hardware/camera2/CaptureResult$Key;', 'SENSOR_TIMESTAMP')][0]

    def emit(a, r0, r1, r2, tag, body):
        """append "<ms> <tag> <body>\\n" to Download/merge.txt. r0..r2 scratch (<16). body(a, rl, rt): line in rl."""
        a.cs(r0, s('Lcom/google/android/libraries/lens/lenslite/api/DownloadEvent;'))
        a.c16(r1, 48); a.c16(r2, 56); a.inv(0x6e, I['sub'], [r0, r1, r2]); a.mro(r0)
        a.inv(0x71, I['pub'], [r0]); a.mro(r0)
        a.cs(r1, s('merge')); a.cs(r2, s('.')); a.inv(0x6e, I['cat'], [r1, r2]); a.mro(r1)
        a.cs(r2, s('txt')); a.inv(0x6e, I['cat'], [r1, r2]); a.mro(r1)
        a.raw(0x0022 | r2 << 8, T('Ljava/io/File;')); a.inv(0x70, I['finit'], [r2, r0, r1])
        a.raw(0x0022 | r0 << 8, T('Ljava/io/FileWriter;')); a.c4(r1, 1); a.inv(0x70, I['fwinit'], [r0, r2, r1])
        a.inv(0x71, I['now'], []); a.raw(0x000b | r1 << 8)                      # move-result-wide r1,r1+1
        assert r2 == r1 + 1
        a.inv(0x71, I['vj'], [r1, r2]); a.mro(r1)
        a.cs(r2, s(' ')); a.inv(0x6e, I['cat'], [r1, r2]); a.mro(r1)
        a.cs(r2, s(tag)); a.inv(0x6e, I['cat'], [r1, r2]); a.mro(r1)
        a.cs(r2, s(' ')); a.inv(0x6e, I['cat'], [r1, r2]); a.mro(r1)
        body(a, r1, r2)
        a.cs(r2, s('\n')); a.inv(0x6e, I['cat'], [r1, r2]); a.mro(r1)
        a.inv(0x6e, I['wr'], [r0, r1]); a.inv(0x6e, I['cl'], [r0])

    def add_block(c, p, fn):
        n0 = len(c.w)
        insert(c, p, fn)
        L = len(c.w) - n0
        c.tries.append([p, L, len(c.handlers)]); c.handlers.append([[], p + L])
        c.tries.sort(key=lambda t: t[0])

    out = {}

    # frame: Ldvm.C entry (v0..v10 free, v12 = ljm)
    m = one(d, 'Ldvm;', 'C'); c = Code(raw, d.code[m])
    def BF(p, na):
        a = S(p)
        def body(a, rl, rt):
            a.inv(0x71, I['vo'], [12]); a.mro(rt); a.inv(0x6e, I['cat'], [rl, rt]); a.mro(rl)
            a.cs(rt, s(' ')); a.inv(0x6e, I['cat'], [rl, rt]); a.mro(rl)
            a.raw(0x0062 | rt << 8, fts); a.inv(0x72, I['ld'], [12, rt]); a.mro(rt)
            a.inv(0x71, I['vo'], [rt]); a.mro(rt); a.inv(0x6e, I['cat'], [rl, rt]); a.mro(rl)
        emit(a, 0, 1, 2, 'frame', body)
        return a.done()
    add_block(c, 0, BF); check(c); out[m] = c.build()

    # exif: Ldub.a pc 53 (v1 = APP1 bytes; v0, v2, v6, v7 free) -> use v6 / v7 pair needs r2=r1+1: r0=v0, r1=v6, r2=v7
    m = [i for i, (cc, pp, nn) in enumerate(d.methods) if cc == 'Ldub;' and nn == 'a' and 'ShotMetadata' in d.mname(i)][0]
    c = Code(raw, d.code[m])
    assert c.w[53] & 0xff == 0x22 and (c.w[53] >> 8) == 7
    def BE(p, na):
        a = S(p)
        def body(a, rl, rt):
            a.inv(0x71, I['vo'], [9]); a.mro(rt); a.inv(0x6e, I['cat'], [rl, rt]); a.mro(rl)   # ShotMetadata ref
        emit(a, 0, 6, 7, 'exif', body)
        return a.done()
    add_block(c, 53, BE); check(c); out[m] = c.build()

    # merge: Lohy.accept pc 326 (v5 = summary string, v4 tag; v0..v3, v6 free)
    m = one(d, 'Lohy;', 'accept'); c = Code(raw, d.code[m])
    hits = [i for i in range(len(c.w) - 7) if c.w[i:i + 2] == [0x0071, I['props']] and c.w[i + 3] == 0x000c
            and c.w[i + 4] == 0x061a and c.w[i + 5] == s('ShotLogData_aborted_get') and c.w[i + 6] & 0xff == 0x72]
    assert len(hits) == 1, hits
    def BM(p, na):
        a = S(p)
        def body(a, rl, rt):
            a.inv(0x6e, I['cat'], [rl, 5]); a.mro(rl)
        emit(a, 0, 1, 2, 'merge', body)
        return a.done()
    add_block(c, hits[0], BM); check(c); out[m] = c.build()

    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
