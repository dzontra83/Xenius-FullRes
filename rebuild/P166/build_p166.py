#!/usr/bin/env python3
"""XENIUS P166 — 50 MP burst follows LMC's "Exposure" menu (pref_aemode_key, per lens).

Before: the 50 MP burst copied ISO + exposure of the trigger (viewfinder) frame; only if ISO > 2400 it moved
to ISO 2400 with a longer exposure, max 125 ms. LMC's Exposure menu (Max ISO / ISO 1600..100 / Max Time /
Time 32 s..1 ms) only reached GCam's own HDR+ frame requests (Lohv.p), never our burst.

Now, in Llei.onCaptureCompleted right after abortCaptures (burst trigger), if MenuValueLens("pref_aemode_key") != 0:
  LMC/AeMode.sGetDesired_exposure_time_ms = exposure_ns / 1e6
  LMC/AeMode.sGetDesired_analog_gain      = ISO * iso100 / 100      (gain units, 1.0 = sensor min ISO)
  LMC/AeMode.sGetDesired_digital_gain     = 1
  LMC/AeMode.isoTimeParametrs(mode)        (LMC's own math: same total exposure, chosen ISO or time;
                                            ISO modes cap time at LMC's max-exposure limit)
  exposure_ns = time_ms * 1e6 ; ISO = round(analog * digital * 100 / iso100)
and the old 2400 / 125 ms rule is skipped. Auto (mode 0) keeps the old rule unchanged.
Bases: P165 (default) or P165L2 (log build). Run: python3 build_p166.py IN.apk OUT.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S

BASES = {'a99b82034b00949b8fe4464473e80c307a0af4fa88efdf76afb2cb0c36973240': 'P165',
         'd14d1ccb786f911570dfaf2fafb3b56a5b72c3440e1f194dc14b94f7cd924df2': 'P165L2'}
fb = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]


def patch(raw):
    h = hashlib.sha256(raw).hexdigest(); assert h in BASES, h
    open('/tmp/_p166.dex', 'wb').write(raw); d = Dex('/tmp/_p166.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    F = lambda n: [i for i, f in enumerate(d.fields) if f == ('LMC/AeMode;', 'F', n)][0]
    T = lambda t: d.types.index(t)
    mvl = M('LMC/pref;', 'MenuValueLens', '(Ljava/lang/String;)I')
    itp = M('LMC/AeMode;', 'isoTimeParametrs', '(I)V')
    lv = M('Ljava/lang/Long;', 'longValue', '()J'); lvo = M('Ljava/lang/Long;', 'valueOf', '(J)Ljava/lang/Long;')
    iv = M('Ljava/lang/Integer;', 'intValue', '()I'); ivo = M('Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    abort = M('Landroid/hardware/camera2/CameraCaptureSession;', 'abortCaptures', '()V')
    FT, FA, FD, F100 = F('sGetDesired_exposure_time_ms'), F('sGetDesired_analog_gain'), F('sGetDesired_digital_gain'), F('iso100')

    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])
    hits = [i for i in range(len(c.w) - 4) if c.w[i:i + 3] == [0x106e, abort, 0x0005] and c.w[i + 3] == 0x0338]
    assert len(hits) == 1, hits
    p = hits[0] + 3                                        # if-eqz v3, -> L960
    t960 = p + c.w[p + 1]
    assert c.w[p + 2] == 0x0238 and c.w[t960] == 0x0338   # if-eqz v2 ; L960: if-eqz v3

    def B(base, na):
        a = S(base); ORIG, SET = na(p), na(t960)
        a.cs(1, sid(d, 'pref_aemode_key')); a.inv(0x71, mvl, [1]); a.mr(1)
        a.b21(0x38, 1, ORIG)                               # Auto -> old rule
        a.b21(0x38, 3, ORIG); a.b21(0x38, 2, ORIG)
        a.raw(0x0060 | 6 << 8, F100); a.c32(4, 0); a.raw(0x002d | 4 << 8, 6 | 4 << 8)   # cmpl-float v4, v6, 0
        a.b21(0x3d, 4, ORIG)                               # iso100 not set (if-lez) -> old rule
        a.raw(0x001f | 2 << 8, T('Ljava/lang/Long;')); a.raw(0x001f | 3 << 8, T('Ljava/lang/Integer;'))
        a.inv(0x6e, lv, [2]); a.raw(0x000b | 6 << 8)       # v6:v7 = exposure ns
        a.raw(0x0085 | 4 << 8 | 6 << 12)                  # long-to-float v4, v6
        a.c32(6, fb(1e6)); a.raw(0x00a9 | 4 << 8, 4 | 6 << 8); a.raw(0x0067 | 4 << 8, FT)
        a.inv(0x6e, iv, [3]); a.mr(4); a.raw(0x0082 | 4 << 8 | 4 << 12)
        a.raw(0x0060 | 6 << 8, F100); a.raw(0x00a8 | 4 << 8, 4 | 6 << 8)
        a.c32(6, fb(100.0)); a.raw(0x00a9 | 4 << 8, 4 | 6 << 8); a.raw(0x0067 | 4 << 8, FA)
        a.c32(4, fb(1.0)); a.raw(0x0067 | 4 << 8, FD)
        a.inv(0x71, itp, [1])
        a.raw(0x0060 | 4 << 8, FT); a.c32(6, fb(1e6)); a.raw(0x00a8 | 4 << 8, 4 | 6 << 8)
        a.raw(0x0088 | 6 << 8 | 4 << 12)                  # float-to-long v6, v4
        a.inv(0x71, lvo, [6, 7]); a.mro(2)
        a.raw(0x0060 | 4 << 8, FA); a.raw(0x0060 | 6 << 8, FD); a.raw(0x00a8 | 4 << 8, 4 | 6 << 8)
        a.c32(6, fb(100.0)); a.raw(0x00a8 | 4 << 8, 4 | 6 << 8)
        a.raw(0x0060 | 6 << 8, F100); a.raw(0x00a9 | 4 << 8, 4 | 6 << 8)
        a.c32(6, fb(0.5)); a.raw(0x00a6 | 4 << 8, 4 | 6 << 8)
        a.raw(0x0087 | 4 << 8 | 4 << 12)                  # float-to-int v4, v4
        a.inv(0x71, ivo, [4]); a.mro(3)
        a.go(SET)
        return a.done()
    insert(c, p, B); check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o), BASES[h]


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new, base = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print(base, '-> classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
