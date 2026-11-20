#!/usr/bin/env python3
"""XENIUS P172L — P172 + Download/merge.txt brightness log.
  frame <ljm> <timestamp> <SENSOR_DYNAMIC_BLACK_LEVEL[4]> <ISO> <exposure ns> <POST_RAW_SENSITIVITY_BOOST>   (Ldvm.C: every
        frame handed to HDR+, 12 MP ZSL and 50 MP burst)
  merge <HDR+ merge summary>                                                                                (Lohy.accept)
Run: python3 build_p172l.py XENIUS_P172_UNSIGNED.apk XENIUS_P172L_LOG_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S
P172_DEX = '6f2fb5dab93b1f99279f4794ca690ca26aeb6c9320571a03953ffd388906cc58'
CR = 'Landroid/hardware/camera2/CaptureResult;'

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P172_DEX, 'classes.dex is not P172'
    open('/tmp/_p172l.dex', 'wb').write(raw); d = Dex('/tmp/_p172l.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    STR = 'Ljava/lang/String;'
    I = dict(cat=M(STR, 'concat', '(Ljava/lang/String;)Ljava/lang/String;'),
             vo=M(STR, 'valueOf', '(Ljava/lang/Object;)Ljava/lang/String;'),
             vj=M(STR, 'valueOf', '(J)Ljava/lang/String;'),
             sub=M(STR, 'substring', '(II)Ljava/lang/String;'),
             af=M('Ljava/util/Arrays;', 'toString', '([F)Ljava/lang/String;'),
             now=M('Ljava/lang/System;', 'currentTimeMillis', '()J'),
             props=M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;'),
             pub=M('Landroid/os/Environment;', 'getExternalStoragePublicDirectory', '(Ljava/lang/String;)Ljava/io/File;'),
             finit=M('Ljava/io/File;', '<init>', '(Ljava/io/File;Ljava/lang/String;)V'),
             fwinit=M('Ljava/io/FileWriter;', '<init>', '(Ljava/io/File;Z)V'),
             wr=M('Ljava/io/Writer;', 'write', '(Ljava/lang/String;)V'),
             cl=M('Ljava/io/Writer;', 'close', '()V'),
             ld=M('Lljm;', 'd', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;'))
    s = lambda x: sid(d, x); T = lambda t: d.types.index(t)
    F = lambda n: [i for i, f in enumerate(d.fields) if f == (CR, 'Landroid/hardware/camera2/CaptureResult$Key;', n)][0]
    def cat(a, rl, rt): a.inv(0x6e, I['cat'], [rl, rt]); a.mro(rl)
    def emit(a, r0, r1, r2, tag, body):
        a.cs(r0, s('Lcom/google/android/libraries/lens/lenslite/api/DownloadEvent;'))
        a.c16(r1, 48); a.c16(r2, 56); a.inv(0x6e, I['sub'], [r0, r1, r2]); a.mro(r0)
        a.inv(0x71, I['pub'], [r0]); a.mro(r0)
        a.cs(r1, s('merge')); a.cs(r2, s('.')); cat(a, r1, r2); a.cs(r2, s('txt')); cat(a, r1, r2)
        a.raw(0x0022 | r2 << 8, T('Ljava/io/File;')); a.inv(0x70, I['finit'], [r2, r0, r1])
        a.raw(0x0022 | r0 << 8, T('Ljava/io/FileWriter;')); a.c4(r1, 1); a.inv(0x70, I['fwinit'], [r0, r2, r1])
        a.inv(0x71, I['now'], []); a.raw(0x000b | r1 << 8); a.inv(0x71, I['vj'], [r1, r2]); a.mro(r1)
        a.cs(r2, s(' ')); cat(a, r1, r2); a.cs(r2, s(tag)); cat(a, r1, r2); a.cs(r2, s(' ')); cat(a, r1, r2)
        body(a, r1, r2)
        a.cs(r2, s('\n')); cat(a, r1, r2); a.inv(0x6e, I['wr'], [r0, r1]); a.inv(0x6e, I['cl'], [r0])
    def add_block(c, p, fn):
        n0 = len(c.w); insert(c, p, fn); L = len(c.w) - n0
        new = []
        for t in c.tries:
            st, cnt, h = t; e = st + cnt
            if st < p + L and e > p:
                if st < p: new.append([st, p - st, h])
                if e > p + L: new.append([p + L, e - p - L, h])
            else: new.append(t)
        new.append([p, L, len(c.handlers)]); c.handlers.append([[], p + L]); c.tries = sorted(new, key=lambda t: t[0])
    out = {}
    # frame
    m = one(d, 'Ldvm;', 'C'); c = Code(raw, d.code[m])
    def fbody(a, rl, rt):
        a.inv(0x71, I['vo'], [12]); a.mro(rt); cat(a, rl, rt)
        for k, conv in (('SENSOR_TIMESTAMP', 'o'), ('SENSOR_DYNAMIC_BLACK_LEVEL', 'f'), ('SENSOR_SENSITIVITY', 'o'),
                        ('SENSOR_EXPOSURE_TIME', 'o'), ('CONTROL_POST_RAW_SENSITIVITY_BOOST', 'o')):
            a.cs(rt, s(' ')); cat(a, rl, rt)
            a.raw(0x0062 | rt << 8, F(k)); a.inv(0x72, I['ld'], [12, rt]); a.mro(rt)
            if conv == 'f':
                a.raw(0x001f | rt << 8, T('[F')); a.inv(0x71, I['af'], [rt]); a.mro(rt)
            else:
                a.inv(0x71, I['vo'], [rt]); a.mro(rt)
            cat(a, rl, rt)
    def LD(pp, na): a = S(pp); emit(a, 0, 1, 2, 'frame', fbody); return a.done()
    add_block(c, 0, LD); check(c); out[m] = c.build()
    # merge
    m = one(d, 'Lohy;', 'accept'); c = Code(raw, d.code[m])
    hits = [i for i in range(len(c.w) - 7) if c.w[i:i + 2] == [0x0071, I['props']] and c.w[i + 3] == 0x000c
            and c.w[i + 4] == 0x061a and c.w[i + 5] == s('ShotLogData_aborted_get') and c.w[i + 6] & 0xff == 0x72]
    assert len(hits) == 1, hits
    def LM(pp, na):
        a = S(pp); emit(a, 0, 1, 2, 'merge', lambda a, rl, rt: cat(a, rl, 5)); return a.done()
    add_block(c, hits[0], LM); check(c); out[m] = c.build()
    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
