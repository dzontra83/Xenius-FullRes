#!/usr/bin/env python3
"""XENIUS P167 — 50 MP burst length cap: long exposures cut the frame count so a burst stays <= ~2.5 s.

Where the burst ISO / exposure are final (Llei.onCaptureCompleted, the 'if-eqz v3' before props.put("ISO")),
store props["SENSOR_EXPOSURE_TIME"] = Integer(max(3, int(2.5e9 / exposure_ns))) (removed when no exposure).
At the frame-count clamp (Llei, before Integer.valueOf(count) -> props["pref_hdrnet_key"] and the capture loop),
count = min(count, that value). Examples: 1/7 s -> 17 frames, 1/4 s -> 10, 0.5 s -> 5, >= 0.84 s -> 3.
Exposures <= 125 ms (2.5 s / 20) never change the count.
Base: P166 (classes.dex 6c80df4e...ecf4). Run: python3 build_p167.py XENIUS_P166_AEMODE_UNSIGNED.apk XENIUS_P167_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S

P166_DEX = '6c80df4e3a2f7b642cb33704a5f4e7f2c342d2cdfa91bc16b742a729825eecf4'
fb = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
BUDGET_NS = 2.5e9


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P166_DEX, 'classes.dex is not P166'
    open('/tmp/_p167.dex', 'wb').write(raw); d = Dex('/tmp/_p167.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    T = lambda t: d.types.index(t)
    put = M('Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    get = M('Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    rem = M('Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;')
    props = M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    lv = M('Ljava/lang/Long;', 'longValue', '()J')
    iv = M('Ljava/lang/Integer;', 'intValue', '()I'); ivo = M('Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    KEY = sid(d, 'SENSOR_EXPOSURE_TIME')

    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])

    # ---- A: store max frames at the ISO/exposure merge point ----
    ha = [i for i in range(len(c.w) - 4) if c.w[i] == 0x0338 and c.w[i + 2] == 0x011a and c.w[i + 3] == sid(d, 'ISO')]
    assert len(ha) == 1, ha
    pa = ha[0]
    def A(base, na):
        a = S(base)
        a.cs(1, KEY)
        a.b21(0x38, 2, 'rm')                               # if-eqz v2 -> remove
        a.raw(0x001f | 2 << 8, T('Ljava/lang/Long;'))
        a.inv(0x6e, lv, [2]); a.raw(0x000b | 6 << 8)       # v6:v7 = ns
        a.raw(0x0085 | 4 << 8 | 6 << 12)                  # long-to-float v4, v6
        a.c32(6, fb(BUDGET_NS)); a.raw(0x00a9 | 6 << 8, 6 | 4 << 8)   # v6 = budget / ns
        a.raw(0x0087 | 6 << 8 | 6 << 12)                  # float-to-int v6, v6
        a.c4(4, 3); a.b22(0x35, 6, 4, 'ok')                # if-ge v6, v4 -> ok
        a.raw(0x0001 | 6 << 8 | 4 << 12)                  # move v6, v4
        a.L('ok')
        a.inv(0x71, ivo, [6]); a.mro(4)
        a.inv(0x72, put, [0, 1, 4])
        a.go('end')
        a.L('rm'); a.inv(0x72, rem, [0, 1])
        a.L('end')
        return a.done()
    insert(c, pa, A); check(c)

    # ---- B: cap the frame count (v0 = count) before Integer.valueOf(v0) -> props['pref_hdrnet_key'] ----
    HN = sid(d, 'pref_hdrnet_key')
    hb = [i for i in range(len(c.w) - 9) if c.w[i:i + 3] == [0x1071, ivo, 0x0000] and c.w[i + 3] == 0x000c
          and c.w[i + 4:i + 6] == [0x0071, props] and c.w[i + 7] == 0x020c and c.w[i + 8] == 0x041a and c.w[i + 9] == HN]
    assert len(hb) == 1, hb
    pb = hb[0]
    def B(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(2)
        a.cs(4, KEY); a.inv(0x72, get, [2, 4]); a.mro(4)
        a.b21(0x38, 4, 'end')
        a.raw(0x001f | 4 << 8, T('Ljava/lang/Integer;'))
        a.inv(0x6e, iv, [4]); a.mr(4)
        a.b22(0x37, 0, 4, 'end')                           # if-le v0, v4 -> end
        a.raw(0x0001 | 0 << 8 | 4 << 12)                  # move v0, v4
        a.L('end')
        return a.done()
    insert(c, pb, B); check(c)

    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
