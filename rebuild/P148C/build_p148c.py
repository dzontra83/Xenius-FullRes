#!/usr/bin/env python3
"""XENIUS P148C — P148B + null-safe FrameMetadata conversion (fixes '0 ms gap / no base frame' on 50 MP bursts).

Log evidence (P148B, 10-frame shot): every 50 MP burst result has CONTROL_AE_STATE/CONTROL_AWB_STATE = null (manual
AE burst). Lohv.k (Camera2 result -> Gcam FrameMetadata) calls Integer.intValue() on these without a null check
-> NullPointerException 'Exception in converting to Gcam FrameMetadata' for every 50 MP frame -> frames carry stale
metadata -> libgcam: 'timestamp gap ... 0.0 ms', 'No base frame candidates', shot aborted.

Fix: before each unguarded intValue() on a CaptureResult key in Lohv.k, substitute a neutral default when null.
Only null values change behaviour (they used to throw), so normal 12 MP frames are unaffected.
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, walk
from build_p149a import Asm, one, mid, rebuild_apk
import build_p149b as B
import build_p148a as A
import build_p148b as K

DEFAULTS = {  # CaptureResult key -> value used when the HAL returns null
    'CONTROL_MODE': 1, 'CONTROL_AE_MODE': 0, 'CONTROL_AE_STATE': 2, 'CONTROL_AE_EXPOSURE_COMPENSATION': 0,
    'CONTROL_AWB_MODE': 1, 'CONTROL_AWB_STATE': 2, 'CONTROL_AF_MODE': 0, 'CONTROL_AF_STATE': 0,
    'CONTROL_AF_TRIGGER': 0, 'FLASH_MODE': 0,
}


def metadata_guards(d, new):
    m = one(d, 'Lohv;', 'k'); c = Code(d.b, d.code[m])
    intValue = mid(d, 'Ljava/lang/Integer;', 'intValue', '()I')
    valueOf = mid(d, 'Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    Integer = d.types.index('Ljava/lang/Integer;')
    keyfields = {i: f[2] for i, f in enumerate(d.fields) if f[0] == 'Landroid/hardware/camera2/CaptureResult;'}
    seq = [(pc, ln) for pc, ln, pay in walk(c.w) if not pay]
    sites = []
    for k in range(4, len(seq)):
        pc = seq[k][0]; w = c.w
        if (w[pc] & 0xff) != 0x6e or w[pc + 1] != intValue: continue
        r = w[pc + 2] & 15
        p1, p2, p3 = seq[k - 1][0], seq[k - 2][0], seq[k - 3][0]
        p4 = seq[k - 4][0]
        # sget-object vR, CaptureResult.KEY ; invoke-interface d(key) ; move-result-object vR ; check-cast vR, Integer ; intValue
        if (w[p1] & 0xff) == 0x1f and (w[p1] >> 8) == r and w[p1 + 1] == Integer and \
           (w[p2] & 0xff) == 0x0c and (w[p2] >> 8) == r and (w[p4] & 0xff) == 0x62 and w[p4 + 1] in keyfields:
            name = keyfields[w[p4 + 1]]
            if name in DEFAULTS: sites.append((pc, r, name))
    found = sorted(n for _, _, n in sites)
    assert set(found) == set(DEFAULTS) and len(found) == len(DEFAULTS), found
    for pc, r, name in sorted(sites, reverse=True):
        def G(p, na, r=r, v=DEFAULTS[name]):
            a = Asm(p)
            a.if_nez(r, na(p))                                   # value present -> original intValue()
            a.w += [0x0012 | r << 8 | (v & 15) << 12]            # const/4 vR, default
            a.inv_static(valueOf, [r]); a.move_result_obj(r)     # vR = Integer.valueOf(default) -> falls into intValue()
            return a.done()
        insert(c, pc, G)
    check(c); new[m] = c
    return [n for _, _, n in sites]


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.extra_methods(d, new)
    K.key40_methods(d, new)
    print('guarded:', metadata_guards(d, new))
    c1 = B.finalize_classes(raw1, d, new)
    c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p148c', 'wb').write(c1); open('classes2.dex.p148c', 'wb').write(c2)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
    print('classes2.dex', len(c2), hashlib.sha256(c2).hexdigest())
