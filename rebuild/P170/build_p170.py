#!/usr/bin/env python3
"""XENIUS P170 — 50 MP brightness: tell HDR+ the 50 MP frames had more exposure (metadata only).

P169/P169B (real burst exposure x0.707 / x0.6) did not bring 50 MP down to 12 MP: HDR+ normalises brightness from each
frame's metadata, so the 50 MP data itself sits higher than the 12 MP ZSL frames at the same metadata.
In Ldvm.p, where a 50 MP frame's FrameMetadata is copied onto the payload frame (actual_analog_gain / applied_digital_gain /
actual_exposure_time_ms), the exposure time handed to HDR+ is multiplied by K (default 1.7 = -0.77 EV output).
Real capture exposure is unchanged (P168 behaviour). XENIUS_K=<factor> overrides.
Base: P168. Run: python3 build_p170.py XENIUS_P168_UNSIGNED.apk XENIUS_P170_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S
P168_DEX = '07948daef5a9e65c1e90def7d694a074590b5381324fec8ecf1bf0fe61c3d76d'
K = float(os.environ.get('XENIUS_K', '1.7'))
fb = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
FM = 'Lcom/google/googlex/gcam/FrameMetadata;'

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P168_DEX, 'classes.dex is not P168'
    open('/tmp/_p170.dex', 'wb').write(raw); d = Dex('/tmp/_p170.dex')
    ets = mid(d, 'Lcom/google/googlex/gcam/GcamModuleJNI;', 'FrameMetadata_actual_exposure_time_ms_set', '(J' + FM + 'F)V')
    ags = mid(d, 'Lcom/google/googlex/gcam/GcamModuleJNI;', 'FrameMetadata_applied_digital_gain_set', '(J' + FM + 'F)V')
    m = [i for i, (c, p, n) in enumerate(d.methods) if c == 'Ldvm;' and n == 'p' and i in d.code]
    assert len(m) == 1; m = m[0]
    c = Code(raw, d.code[m])
    # anchor: digital_gain_set {v13,v14,v7,v15} immediately followed by exposure_time_ms_set {v13,v14,v7,v1}
    hits = [i for i in range(len(c.w) - 6) if c.w[i] == 0x4071 and c.w[i + 1] == ags and c.w[i + 3] == 0x4071 and c.w[i + 4] == ets]
    assert len(hits) == 1, hits
    p = hits[0] + 3
    assert c.w[p + 2] == (13 | 14 << 4 | 7 << 8 | 1 << 12), hex(c.w[p + 2])     # {v13, v14, v7, v1}
    def B(base, na):
        a = S(base)
        a.c32(9, fb(K)); a.raw(0x00a8 | 1 << 8, 1 | 9 << 8)   # mul-float v1, v1, v9
        return a.done()
    insert(c, p, B); check(c)
    o = bytearray(relocate(raw, {m: c.build()})); fix_hdr(o)
    return bytes(o)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('K', K, 'classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
