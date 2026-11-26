#!/usr/bin/env python3
"""XENIUS P166L2 — P166L + 'expo <ISO> <exposure ns>' line in Download/merge.txt for every 50 MP burst
(written where the burst ISO / exposure are final, i.e. after the Auto rule or the LMC Exposure-menu math).
Run: python3 build_p166l2.py XENIUS_P166L_AEMODE_LOG_UNSIGNED.apk XENIUS_P166L2_AEMODE_LOG_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_p165l as L
from dex import Dex
from dexpatch import Code, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S

P166L_DEX = '24e5b9eede9e4dbe32ec59ab8ad49988d790031c5f541eabb8d8017d1ebff704'


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P166L_DEX
    open('/tmp/_p166l2.dex', 'wb').write(raw); d = Dex('/tmp/_p166l2.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    STR = 'Ljava/lang/String;'
    I = dict(cat=M(STR, 'concat', '(Ljava/lang/String;)Ljava/lang/String;'),
             vo=M(STR, 'valueOf', '(Ljava/lang/Object;)Ljava/lang/String;'),
             vj=M(STR, 'valueOf', '(J)Ljava/lang/String;'),
             sub=M(STR, 'substring', '(II)Ljava/lang/String;'),
             now=M('Ljava/lang/System;', 'currentTimeMillis', '()J'),
             pub=M('Landroid/os/Environment;', 'getExternalStoragePublicDirectory', '(Ljava/lang/String;)Ljava/io/File;'),
             finit=M('Ljava/io/File;', '<init>', '(Ljava/io/File;Ljava/lang/String;)V'),
             fwinit=M('Ljava/io/FileWriter;', '<init>', '(Ljava/io/File;Z)V'),
             wr=M('Ljava/io/Writer;', 'write', '(Ljava/lang/String;)V'),
             cl=M('Ljava/io/Writer;', 'close', '()V'))
    s = lambda x: sid(d, x); T = lambda t: d.types.index(t)
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
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])
    # target: 'if-eqz v3' followed by const-string v1 'ISO' (the common point after both exposure paths)
    hits = [i for i in range(len(c.w) - 4) if c.w[i] == 0x0338 and c.w[i + 2] == 0x011a and c.w[i + 3] == s('ISO')]
    assert len(hits) == 1, hits
    p = hits[0]
    def body(a, rl, rt):
        a.inv(0x71, I['vo'], [3]); a.mro(rt); cat(a, rl, rt)
        a.cs(rt, s(' ')); cat(a, rl, rt)
        a.inv(0x71, I['vo'], [2]); a.mro(rt); cat(a, rl, rt)
    def B(pp, na): a = S(pp); emit(a, 1, 6, 7, 'exif', body); return a.done()
    L_add = None
    # reuse P165L's add_block semantics (split enclosing try)
    from dexpatch import insert
    n0 = len(c.w); insert(c, p, B); Ln = len(c.w) - n0
    new = []
    for t in c.tries:
        st, cnt, h = t; e = st + cnt
        if st < p + Ln and e > p:
            if st < p: new.append([st, p - st, h])
            if e > p + Ln: new.append([p + Ln, e - p - Ln, h])
        else: new.append(t)
    new.append([p, Ln, len(c.handlers)]); c.handlers.append([[], p + Ln]); c.tries = sorted(new, key=lambda t: t[0])
    check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
