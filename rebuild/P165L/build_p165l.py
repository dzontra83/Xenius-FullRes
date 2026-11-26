#!/usr/bin/env python3
"""XENIUS P165L — P164B + 50 MP pipeline log Download/merge.txt (diagnostic, no ADB needed).

Lines "<epoch ms> <event> <detail>", each write inside its own catch-all try:
  applied   Llfe.e / Llel.c : 8192x6144 RAW reader added to the session
  rejected  Llfe.e / Llel.c : adding it threw (exception text)
  capture   Llei.onCaptureCompleted, burst trigger (applied==7): camera id
  error     Llei burst build/submit threw (exception text)
  failed    Llei.onCaptureFailed (burst callback): CaptureFailure reason (0 = HAL error, 1 = flushed)
  image     Lleu.onImageAvailable: a 50 MP frame arrived (width x height)
  frame     Ldvm.C: frame handed to HDR+
  merge     Lohy.accept: HDR+ merge summary
Run: python3 build_p165l.py XENIUS_P164B_20F_UNSIGNED.apk XENIUS_P165L_LOG_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S

P164B_DEX = 'dd43b3d2d9c90fb002a631eb95732c31b6cae22f41748d58ef079b10d6a22ea5'
CR = 'Landroid/hardware/camera2/CaptureResult;'


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P164B_DEX, 'classes.dex is not P164B'
    open('/tmp/_p165l.dex', 'wb').write(raw); d = Dex('/tmp/_p165l.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    STR = 'Ljava/lang/String;'
    I = dict(
        cat=M(STR, 'concat', '(Ljava/lang/String;)Ljava/lang/String;'),
        vo=M(STR, 'valueOf', '(Ljava/lang/Object;)Ljava/lang/String;'),
        vj=M(STR, 'valueOf', '(J)Ljava/lang/String;'),
        sub=M(STR, 'substring', '(II)Ljava/lang/String;'),
        its=M('Ljava/lang/Integer;', 'toString', '(I)Ljava/lang/String;'),
        tts=M('Ljava/lang/Throwable;', 'toString', '()Ljava/lang/String;'),
        dev=M('Landroid/hardware/camera2/CameraCaptureSession;', 'getDevice', '()Landroid/hardware/camera2/CameraDevice;'),
        cid=M('Landroid/hardware/camera2/CameraDevice;', 'getId', '()Ljava/lang/String;'),
        iw=M('Landroid/media/Image;', 'getWidth', '()I'),
        ih=M('Landroid/media/Image;', 'getHeight', '()I'),
        rsn=M('Landroid/hardware/camera2/CaptureFailure;', 'getReason', '()I'),
        now=M('Ljava/lang/System;', 'currentTimeMillis', '()J'),
        props=M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;'),
        pub=M('Landroid/os/Environment;', 'getExternalStoragePublicDirectory', '(Ljava/lang/String;)Ljava/io/File;'),
        finit=M('Ljava/io/File;', '<init>', '(Ljava/io/File;Ljava/lang/String;)V'),
        fwinit=M('Ljava/io/FileWriter;', '<init>', '(Ljava/io/File;Z)V'),
        wr=M('Ljava/io/Writer;', 'write', '(Ljava/lang/String;)V'),
        cl=M('Ljava/io/Writer;', 'close', '()V'),
        ld=M('Lljm;', 'd', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;'))
    s = lambda x: sid(d, x)
    T = lambda t: d.types.index(t)
    fts = [i for i, f in enumerate(d.fields) if f == (CR, 'Landroid/hardware/camera2/CaptureResult$Key;', 'SENSOR_TIMESTAMP')][0]

    def cat(a, rl, rt): a.inv(0x6e, I['cat'], [rl, rt]); a.mro(rl)

    def emit(a, r0, r1, r2, tag, body):
        assert r2 == r1 + 1 and max(r0, r1, r2) < 16
        a.cs(r0, s('Lcom/google/android/libraries/lens/lenslite/api/DownloadEvent;'))
        a.c16(r1, 48); a.c16(r2, 56); a.inv(0x6e, I['sub'], [r0, r1, r2]); a.mro(r0)
        a.inv(0x71, I['pub'], [r0]); a.mro(r0)
        a.cs(r1, s('merge')); a.cs(r2, s('.')); cat(a, r1, r2)
        a.cs(r2, s('txt')); cat(a, r1, r2)
        a.raw(0x0022 | r2 << 8, T('Ljava/io/File;')); a.inv(0x70, I['finit'], [r2, r0, r1])
        a.raw(0x0022 | r0 << 8, T('Ljava/io/FileWriter;')); a.c4(r1, 1); a.inv(0x70, I['fwinit'], [r0, r2, r1])
        a.inv(0x71, I['now'], []); a.raw(0x000b | r1 << 8)
        a.inv(0x71, I['vj'], [r1, r2]); a.mro(r1)
        a.cs(r2, s(' ')); cat(a, r1, r2)
        a.cs(r2, s(tag)); cat(a, r1, r2)
        a.cs(r2, s(' ')); cat(a, r1, r2)
        body(a, r1, r2)
        a.cs(r2, s('\n')); cat(a, r1, r2)
        a.inv(0x6e, I['wr'], [r0, r1]); a.inv(0x6e, I['cl'], [r0])

    def add_block(c, p, fn):
        n0 = len(c.w); insert(c, p, fn); L = len(c.w) - n0
        new = []
        for t in c.tries:
            st, cnt, h = t; e = st + cnt
            if st < p + L and e > p:                       # enclosing try: split around the block
                if st < p: new.append([st, p - st, h])
                if e > p + L: new.append([p + L, e - p - L, h])
            else:
                new.append(t)
        new.append([p, L, len(c.handlers)]); c.handlers.append([[], p + L])
        c.tries = sorted(new, key=lambda t: t[0])

    def hook(m, p, regs, tag, body, expect=None):
        c = Code(raw, d.code[m])
        if expect: assert expect(c.w, p), (d.mname(m), p, hex(c.w[p]))
        def B(pp, na):
            a = S(pp); emit(a, *regs, tag, body); return a.done()
        add_block(c, p, B); check(c); return c

    nobody = lambda a, rl, rt: None
    def exc(r):
        def b(a, rl, rt): a.inv(0x6e, I['tts'], [r]); a.mro(rt); cat(a, rl, rt)
        return b

    out = {}
    def put(m, c): out[m] = c.build()

    # Llfe.e: applied @148 (const-string v6 'RAW50_REQ'), rejected @158 (after move-exception v4)
    m = one(d, 'Llfe;', 'e'); c = Code(raw, d.code[m])
    assert c.w[148] == 0x061a and c.w[149] == s('RAW50_REQ') and c.w[157] == 0x040d
    def BA(pp, na): a = S(pp); emit(a, 5, 6, 7, 'applied', nobody); return a.done()
    def BR(pp, na): a = S(pp); emit(a, 5, 6, 7, 'rejected', exc(4)); return a.done()
    add_block(c, 158, BR); add_block(c, 148, BA); check(c); put(m, c)

    # Llel.c: applied @178, rejected @191 (move-exception v8 @190)
    m = one(d, 'Llel;', 'c'); c = Code(raw, d.code[m])
    assert c.w[178] == 0x0a1a and c.w[179] == s('RAW50_REQ') and c.w[190] == 0x080d
    def CA(pp, na): a = S(pp); emit(a, 9, 10, 11, 'applied', nobody); return a.done()
    def CR_(pp, na): a = S(pp); emit(a, 9, 10, 11, 'rejected', exc(8)); return a.done()
    add_block(c, 191, CR_); add_block(c, 178, CA); check(c); put(m, c)

    # Llei.onCaptureCompleted: capture @847 (burst trigger), error @1423 (move-exception v0 @1422)
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])
    assert c.w[1422] == 0x000d and c.w[847] == 0x0071 and c.w[848] == I['props']
    def camid(a, rl, rt):
        a.inv(0x6e, I['dev'], [5]); a.mro(rt); a.inv(0x6e, I['cid'], [rt]); a.mro(rt); cat(a, rl, rt)
    def LE(pp, na): a = S(pp); emit(a, 1, 2, 3, 'error', exc(0)); return a.done()
    def LC(pp, na): a = S(pp); emit(a, 0, 1, 2, 'capture', camid); return a.done()
    add_block(c, 1423, LE); add_block(c, 847, LC); check(c); put(m, c)

    # Llei.onCaptureFailed: failed @25 (burst path, Llei.a == null)
    m = one(d, 'Llei;', 'onCaptureFailed'); c = Code(raw, d.code[m])
    assert c.w[25] == 0x0013 | 0 and c.w[26] == 72
    def reason(a, rl, rt):
        a.inv(0x6e, I['rsn'], [4]); a.mr(rt); a.inv(0x71, I['its'], [rt]); a.mro(rt); cat(a, rl, rt)
    def LF(pp, na): a = S(pp); emit(a, 0, 2, 3, 'failed', reason); return a.done()
    add_block(c, 25, LF); check(c); put(m, c)

    # Lleu.onImageAvailable: image @22 (v2 = Image, 50 MP reader)
    m = one(d, 'Lleu;', 'onImageAvailable'); c = Code(raw, d.code[m])
    assert c.w[22] == 0x106e and c.w[23] == I['iw']
    def wh(a, rl, rt):
        a.inv(0x6e, I['iw'], [2]); a.mr(rt); a.inv(0x71, I['its'], [rt]); a.mro(rt); cat(a, rl, rt)
        a.cs(rt, s('x')); cat(a, rl, rt)
        a.inv(0x6e, I['ih'], [2]); a.mr(rt); a.inv(0x71, I['its'], [rt]); a.mro(rt); cat(a, rl, rt)
    def LI(pp, na): a = S(pp); emit(a, 3, 4, 5, 'image', wh); return a.done()
    add_block(c, 22, LI); check(c); put(m, c)

    # Ldvm.C entry: frame (v12 = ljm)
    m = one(d, 'Ldvm;', 'C')
    def fbody(a, rl, rt):
        a.inv(0x71, I['vo'], [12]); a.mro(rt); cat(a, rl, rt)
        a.cs(rt, s(' ')); cat(a, rl, rt)
        a.raw(0x0062 | rt << 8, fts); a.inv(0x72, I['ld'], [12, rt]); a.mro(rt)
        a.inv(0x71, I['vo'], [rt]); a.mro(rt); cat(a, rl, rt)
    c = Code(raw, d.code[m])
    def LD(pp, na): a = S(pp); emit(a, 0, 1, 2, 'frame', fbody); return a.done()
    add_block(c, 0, LD); check(c); put(m, c)

    # Lohy.accept merge summary
    m = one(d, 'Lohy;', 'accept'); c = Code(raw, d.code[m])
    hits = [i for i in range(len(c.w) - 7) if c.w[i:i + 2] == [0x0071, I['props']] and c.w[i + 3] == 0x000c
            and c.w[i + 4] == 0x061a and c.w[i + 5] == s('ShotLogData_aborted_get') and c.w[i + 6] & 0xff == 0x72]
    assert len(hits) == 1, hits
    def LM(pp, na):
        a = S(pp); emit(a, 0, 1, 2, 'merge', lambda a, rl, rt: cat(a, rl, 5)); return a.done()
    add_block(c, hits[0], LM); check(c); put(m, c)

    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
