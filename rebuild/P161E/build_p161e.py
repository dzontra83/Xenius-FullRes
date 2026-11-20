#!/usr/bin/env python3
"""XENIUS P161E — diagnostic build on top of P160 that writes its own file (no ADB needed). Logs only.

Ldvm.C (gyro samples for a frame, called once per HDR+ payload frame, 12 MP and 50 MP), at entry, all inside a
catch-all try (any error -> skipped, the shot continues):
  line = <result object class (Llfc = 50 MP frame)>:<SENSOR_TIMESTAMP>:<System.nanoTime>:<elapsedRealtimeNanos>
         :<gyro provider present>:<SENSOR_NOISE_PROFILE>:<SENSOR_DYNAMIC_BLACK_LEVEL>
  Log.w("gyro", line) and append line to Download/gyro_metadata.txt

Run: python3 build_p161e.py XENIUS_P160_NOAFLOCK_UNSIGNED.apk XENIUS_P161E_DIAGFILE_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p157 import A

P160_DEX = '30d9336bbd86e082c1b9adaf850362878e65fb7d93aa1bb1aff572173278efcf'
CR = 'Landroid/hardware/camera2/CaptureResult;'


def fid(d, cls, name):
    r = [i for i, f in enumerate(d.fields) if f[0] == cls and f[2] == name]; assert len(r) == 1, name; return r[0]


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P160_DEX, 'classes.dex is not P160'
    open('/tmp/_p161e.dex', 'wb').write(raw); d = Dex('/tmp/_p161e.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    T = lambda t: d.types.index(t)
    S = lambda s: sid(d, s)
    ld = M('Lljm;', 'd', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;')
    vo = M('Ljava/lang/String;', 'valueOf', '(Ljava/lang/Object;)Ljava/lang/String;')
    vj = M('Ljava/lang/String;', 'valueOf', '(J)Ljava/lang/String;')
    vz = M('Ljava/lang/String;', 'valueOf', '(Z)Ljava/lang/String;')
    cat = M('Ljava/lang/String;', 'concat', '(Ljava/lang/String;)Ljava/lang/String;')
    sub = M('Ljava/lang/String;', 'substring', '(II)Ljava/lang/String;')
    nano = M('Ljava/lang/System;', 'nanoTime', '()J')
    boot = M('Landroid/os/SystemClock;', 'elapsedRealtimeNanos', '()J')
    pget = M('Lpii;', 'get', '()Ljava/lang/Object;')
    ng = M('Lniz;', 'g', '()Z')
    lw = M('Landroid/util/Log;', 'w', '(Ljava/lang/String;Ljava/lang/String;)I')
    deep = M('Ljava/util/Arrays;', 'deepToString', '([Ljava/lang/Object;)Ljava/lang/String;')
    fts = M('Ljava/util/Arrays;', 'toString', '([F)Ljava/lang/String;')
    pubdir = M('Landroid/os/Environment;', 'getExternalStoragePublicDirectory', '(Ljava/lang/String;)Ljava/io/File;')
    finit = M('Ljava/io/File;', '<init>', '(Ljava/io/File;Ljava/lang/String;)V')
    fwinit = M('Ljava/io/FileWriter;', '<init>', '(Ljava/io/File;Z)V')
    wwrite = M('Ljava/io/Writer;', 'write', '(Ljava/lang/String;)V')
    wclose = M('Ljava/io/Writer;', 'close', '()V')
    ids = [S(x) for x in (':', 'gyro', 'Lcom/google/android/libraries/lens/lenslite/api/DownloadEvent;', '_', 'metadata', '.', 'txt', '\n')]
    assert max(ids) < 65536
    COLON, TG, DLE, US, MD, DOT, TXT, NL = ids

    m = one(d, 'Ldvm;', 'C'); c = Code(raw, d.code[m])
    assert not c.tries and c.regs == 13 and c.ins == 2
    def BC(p, na):
        a = A(p)
        a.label('t0')
        a.inv(0x71, vo, [12]); a.mresobj(1)                                          # class@hash of the result
        a.w += [0x0062, fid(d, CR, 'SENSOR_TIMESTAMP')]; a.inv(0x72, ld, [12, 0]); a.mresobj(0)
        a.inv(0x71, vo, [0]); a.mresobj(4); a.cstr(8, COLON)
        a.inv(0x6e, cat, [1, 8]); a.mresobj(1); a.inv(0x6e, cat, [1, 4]); a.mresobj(1)
        a.inv(0x71, nano, []); a.w += [0x020b]; a.inv(0x71, vj, [2, 3]); a.mresobj(4)
        a.inv(0x6e, cat, [1, 8]); a.mresobj(1); a.inv(0x6e, cat, [1, 4]); a.mresobj(1)
        a.inv(0x71, boot, []); a.w += [0x020b]; a.inv(0x71, vj, [2, 3]); a.mresobj(4)
        a.inv(0x6e, cat, [1, 8]); a.mresobj(1); a.inv(0x6e, cat, [1, 4]); a.mresobj(1)
        a.w += [0x0054 | 6 << 8 | 11 << 12, fid(d, 'Ldvm;', 'y')]; a.inv(0x72, pget, [6]); a.mresobj(6)
        a.w += [0x061f, T('Lniz;')]; a.inv(0x6e, ng, [6]); a.w += [0x070a]; a.inv(0x71, vz, [7]); a.mresobj(4)
        a.inv(0x6e, cat, [1, 8]); a.mresobj(1); a.inv(0x6e, cat, [1, 4]); a.mresobj(1)
        a.w += [0x0062, fid(d, CR, 'SENSOR_NOISE_PROFILE')]; a.inv(0x72, ld, [12, 0]); a.mresobj(0)
        a.w += [0x001f, T('[Ljava/lang/Object;')]; a.inv(0x71, deep, [0]); a.mresobj(4)
        a.inv(0x6e, cat, [1, 8]); a.mresobj(1); a.inv(0x6e, cat, [1, 4]); a.mresobj(1)
        a.w += [0x0062, fid(d, CR, 'SENSOR_DYNAMIC_BLACK_LEVEL')]; a.inv(0x72, ld, [12, 0]); a.mresobj(0)
        a.w += [0x001f, T('[F')]; a.inv(0x71, fts, [0]); a.mresobj(4)
        a.inv(0x6e, cat, [1, 8]); a.mresobj(1); a.inv(0x6e, cat, [1, 4]); a.mresobj(1)
        a.cstr(8, TG); a.inv(0x71, lw, [8, 1])
        # Download/gyro_metadata.txt (append)
        a.cstr(4, DLE); a.w += [0x3212, 0x3612]                                       # const/4 v2,3 ; const/4 v6,3 (placeholders)
        a.w[-2] = 0x0213; a.w[-1] = 48                                                # const/16 v2, 48
        a.w += [0x0613, 56]                                                           # const/16 v6, 56
        a.inv(0x6e, sub, [4, 2, 6]); a.mresobj(4)
        a.inv(0x71, pubdir, [4]); a.mresobj(4)
        a.cstr(5, TG); a.cstr(6, US); a.inv(0x6e, cat, [5, 6]); a.mresobj(5)
        a.cstr(6, MD); a.inv(0x6e, cat, [5, 6]); a.mresobj(5)
        a.cstr(6, DOT); a.inv(0x6e, cat, [5, 6]); a.mresobj(5)
        a.cstr(6, TXT); a.inv(0x6e, cat, [5, 6]); a.mresobj(5)
        a.w += [0x0322, T('Ljava/io/File;')]; a.inv(0x70, finit, [3, 4, 5])          # new File(dir, name)
        a.w += [0x0722, T('Ljava/io/FileWriter;')]; a.w += [0x1612]                  # new FileWriter ; const/4 v6, 1
        a.inv(0x70, fwinit, [7, 3, 6])
        a.cstr(8, NL); a.inv(0x6e, cat, [1, 8]); a.mresobj(1)
        a.inv(0x6e, wwrite, [7, 1]); a.inv(0x6e, wclose, [7])
        a.label('t1')
        a.label('end')
        return a.done()
    n0 = len(c.w)
    probe = A(0)
    insert(c, 0, BC)
    L = len(c.w) - n0
    # try range [0, t1) -> catch-all at L (the original first instruction)
    blk = BC(0, lambda x: x)
    t1 = len(blk)                       # unpadded block length = address of label t1
    c.tries.append([0, t1, 0]); c.handlers.append([[], L])
    check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
