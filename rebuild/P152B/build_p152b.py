#!/usr/bin/env python3
"""XENIUS P152B — P152A + ISO cap for the 50 MP burst.

The burst copies ISO/exposure from the trigger frame (manual AE). libgcam: gain = ISO/50, max 48x ->
dark shots at ISO 2458..3200 exceeded the limit ('too much gain', 'This should never happen').
I1 Llei.onCaptureCompleted: if ISO > 2400 -> ISO = 2400 and exposure *= ISO/2400 (same brightness), exposure <= 125 ms.
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dexpatch import insert, check
from build_p149a import Asm, one, mid, sid, rebuild_apk
import build_p149b as B, build_p148a as A, build_p148b as K, build_p148c as C, build_p148d as D, build_p152a as P

ISO_CAP, MAX_EXP_NS = 2400, 125_000_000


def iso_cap(d, new):
    c = new[one(d, 'Llei;', 'onCaptureCompleted')]
    s_iso = sid(d, 'ISO')
    p = [i for i in range(len(c.w) - 4) if c.w[i:i + 4] == [0x0338, 8, 0x011a, s_iso]]
    assert len(p) == 1, p
    p = p[0]
    Long, Integer = d.types.index('Ljava/lang/Long;'), d.types.index('Ljava/lang/Integer;')
    longValue = mid(d, 'Ljava/lang/Long;', 'longValue', '()J'); lvalueOf = mid(d, 'Ljava/lang/Long;', 'valueOf', '(J)Ljava/lang/Long;')
    intValue = mid(d, 'Ljava/lang/Integer;', 'intValue', '()I'); ivalueOf = mid(d, 'Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    def I1(q, na):
        a = Asm(q)
        a.if_eqz(3, na(p)); a.if_eqz(2, na(p))                    # no ISO / exposure -> unchanged
        a.check_cast(3, Integer); a.check_cast(2, Long)
        a.inv_virtual(intValue, [3]); a.move_result(1)
        a.w += [0x0413, ISO_CAP]
        a.fix.append((len(a.w), a.pc(), na(p), '22t')); a.w += [0x0037 | (1 << 8) | (4 << 12), 0]
        a.inv_virtual(longValue, [2]); a.w += [0x060b]
        a.w += [0x1281, 0x26bd, 0x0216, ISO_CAP, 0x26be]
        a.w += [0x0217, MAX_EXP_NS & 0xffff, MAX_EXP_NS >> 16]
        a.w += [0x0131, 0x0206]                                    # cmp-long v1, v6, v2
        a.fix.append((len(a.w), a.pc(), 'ok', '21t')); a.w += [0x013d, 0]   # if-lez v1, ok
        a.w += [0x2604]                                            # move-wide v6, v2  (clamp)
        a.label('ok')
        a.invoke(0x71, lvalueOf, [6, 7]); a.move_result_obj(2)     # v2 = Long(exposure')
        a.w += [0x0113, ISO_CAP]                                   # const/16 v1, 2400
        a.inv_static(ivalueOf, [1]); a.move_result_obj(3)          # v3 = Integer(2400)
        a.goto32(na(p))
        return a.done()
    insert(c, p, I1); check(c)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.extra_methods(d, new); K.key40_methods(d, new); C.metadata_guards(d, new); D.d_methods(d, new); P.p152_methods(d, new); iso_cap(d, new)
    c1 = B.finalize_classes(raw1, d, new); c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p152b', 'wb').write(c1)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
