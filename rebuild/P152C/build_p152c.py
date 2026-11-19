#!/usr/bin/env python3
"""XENIUS P152C — P152B + probe file only for 50 MP burst frames.

K13's RAW50_C_PROBE1.txt writers in Llei.onCaptureStarted / onCaptureCompleted were gated only on 'RAW50_REPEAT set
and request != trigger request'. RAW50_REPEAT stays set after the first shot, so every preview frame of every later
session (30 fps) was appended to the file on the main thread. Now they also require the listener-less burst callback
(Llei.a == null), i.e. only the 50 MP burst frames are written, like the P152A result store.
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check
from build_p149a import Asm, one, sid, rebuild_apk
import build_p149b as B, build_p148a as A, build_p148b as K, build_p148c as C, build_p148d as D, build_p152a as P, build_p152b as I


def probe_gate(d, new):
    f_a = d.fields.index(('Llei;', 'Lldg;', 'a')); s_dl = sid(d, 'Lcom/google/android/libraries/lens/lenslite/api/DownloadEvent;')
    def gate(c, ifeq_word, this_reg, scratch):
        p = [i for i in range(len(c.w) - 4) if c.w[i] == ifeq_word and c.w[i + 2] == 0x001a and c.w[i + 3] == s_dl]
        assert len(p) == 1, p
        p = p[0]; off = c.w[p + 1] - 0x10000 if c.w[p + 1] & 0x8000 else c.w[p + 1]; skip = p + off
        def G(q, na):
            a = Asm(q)
            a.w += [0x0054 | (scratch << 8) | (this_reg << 12), f_a]     # iget-object vS, vThis, Llei;->a
            a.if_nez(scratch, na(skip))                                 # GCam listener callback -> no probe write
            return a.done()
        insert(c, p + 2, G); check(c)
    gate(new[one(d, 'Llei;', 'onCaptureCompleted')], 0x0632, 4, 0)    # if-eq v6, v0
    m = one(d, 'Llei;', 'onCaptureStarted'); c = Code(d.b, d.code[m])
    gate(c, 0x4b32, 9, 4); new[m] = c                                  # if-eq v11, v4


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.extra_methods(d, new); K.key40_methods(d, new); C.metadata_guards(d, new); D.d_methods(d, new)
    P.p152_methods(d, new); I.iso_cap(d, new); probe_gate(d, new)
    c1 = B.finalize_classes(raw1, d, new); c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p152c', 'wb').write(c1)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
