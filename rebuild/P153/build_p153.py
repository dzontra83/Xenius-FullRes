#!/usr/bin/env python3
"""XENIUS P153 — P152C + speed (debug logging off in per-frame paths, no 50 MP engine in 12 MP) + 50 MP HDR+ up to 30 frames (TEST).

S1 Log.i / Log.d calls in per-frame camera/HDR+ methods become no-ops (K13 probes logged ~1000-1900 lines/s while
   shooting). Kept: VIVO_GATE, RESOLUTION_SWITCH tags, the merge summary (Lohy.accept), every Log.e / Log.w.
   Where the int result was kept (move-result vX) it becomes const/4 vX, 0 so register types stay valid.
S2 Ldux.get: RES OFF -> do not build the second (8192x6144) GCam engine (faster start, less RAM in 12 MP).
F30 frame cap 30: 30 slots, clamp 2..30, RAW50 maxImages 30, first-frame wait up to 10 s.
"""
import sys, os, struct, zipfile, hashlib, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, walk
from build_p149a import Asm, one, mid, sid, rebuild_apk
import build_p149b as B, build_p148a as A, build_p148b as K, build_p148c as C, build_p148d as D
import build_p152a as P, build_p152b as I, build_p152c as Q

MAXF = 30
KEEP_TAGS = {'VIVO_GATE', 'RESOLUTION_SWITCH'}
QUIET = {  # class -> method names (all overloads with code)
    'Laqv;': ['onCaptureCompleted', 'onCaptureProgressed'], 'Laqw;': ['onCaptureCompleted', 'onCaptureProgressed'],
    'Laqz;': ['onCaptureCompleted', 'onCaptureProgressed', 'a'],
    'Llei;': ['onCaptureStarted', 'onCaptureCompleted', 'onCaptureProgressed'],
    'Laue;': ['a'], 'Lleo;': ['a'], 'Lleu;': ['onImageAvailable'],
    'Ldvm;': ['p', 'E', 's', 'k', 'n', 't', 'x', 'y'], 'Lohv;': ['o', 'p'], 'Llel;': ['h', 'c'],
}


def pick_extra(d, n):
    from dexpatch import walk as wk
    used = set()
    for mi in d.code:
        _, w = d.insns(mi)
        for pc, ln, pay in wk(list(w)):
            if not pay and (w[pc] & 0xff) == 0x1a: used.add(w[pc + 1])
    keep = list(A.EXTRA)
    for i, s in enumerate(d.strings):
        if len(keep) >= n: break
        if s.startswith('ShotLogData_') and s.endswith('_get') and i not in used and i < 65536 and s not in keep \
                and s not in A.SLOT:
            keep.append(s)
    assert len(keep) == n
    return keep


def quiet(c, d, logs):
    """In-place: Log.i/d(tag,msg) -> nop (unless tag in KEEP_TAGS). Returns count."""
    w = c.w; seq = [(pc, ln) for pc, ln, pay in walk(w) if not pay]
    pos = {pc: k for k, (pc, ln) in enumerate(seq)}
    keep_ids = {sid(d, t) for t in KEEP_TAGS if t in d.strings}
    n = 0
    for k, (pc, ln) in enumerate(seq):
        if (w[pc] & 0xff) != 0x71 or w[pc + 1] not in logs or (w[pc] >> 12) != 2: continue
        tag = w[pc + 2] & 15
        keep = False
        for j in range(k - 1, max(-1, k - 10), -1):          # nearest earlier write of the tag register
            q = seq[j][0]; o = w[q] & 0xff
            if o == 0x1a and (w[q] >> 8) == tag:
                keep = w[q + 1] in keep_ids; break
        if keep: continue
        nxt = seq[k + 1][0] if k + 1 < len(seq) else None
        if nxt is not None and (w[nxt] & 0xff) == 0x0a:
            r = w[nxt] >> 8
            if r >= 16: continue
            w[nxt] = 0x0012 | (r << 8)                         # move-result vR -> const/4 vR, 0
        w[pc] = w[pc + 1] = w[pc + 2] = 0
        n += 1
    return n


def speed(d, new):
    logs = {mid(d, 'Landroid/util/Log;', 'i', '(Ljava/lang/String;Ljava/lang/String;)I'),
            mid(d, 'Landroid/util/Log;', 'd', '(Ljava/lang/String;Ljava/lang/String;)I')}
    total = 0
    for cls, names in QUIET.items():
        for n in names:
            for m in d.find(cls, n):
                if m not in d.code: continue
                c = new.get(m) or Code(d.b, d.code[m])
                k = quiet(c, d, logs)
                if k:
                    check(c); new[m] = c; total += k
    # S2: Ldux.get — RES OFF -> skip the second GCam engine
    m = one(d, 'Ldux;', 'get'); c = new.get(m) or Code(d.b, d.code[m])
    menu = mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    p = [i for i in range(len(c.w) - 6) if c.w[i] == 0x0071 and c.w[i + 1] == mid(d, 'Ljava/lang/System;', 'getProperties', ')Ljava/util/Properties;')
         and c.w[i + 3] == 0x000c and c.w[i + 4] == 0x011a and c.w[i + 5] == sid(d, 'Gcam_GetNumCameras')]
    assert len(p) >= 1, p
    p = p[0]
    ret = [i for i in range(len(c.w)) if c.w[i] == 0x1011 and c.w[i] & 0xff == 0x11]   # return-object v16 (11x, vAA=16)
    ret = [i for i in range(len(c.w)) if c.w[i] == (0x11 | 16 << 8)]
    assert ret, 'return-object v16'
    def S2(q, na):
        a = Asm(q)
        a.const_string(0, sid(d, 'pref_upscale_key')); a.inv_static(menu, [0]); a.move_result(0)
        a.if_eqz(0, na(ret[0]))
        return a.done()
    insert(c, p, S2); check(c); new[m] = c
    return total


def quiet_classes2(raw):
    """In-place on the P149B classes2.dex: LMC/jwb.CCT_WB debug logs."""
    out = bytearray(raw); open('/tmp/_c2q.dex', 'wb').write(raw); d = Dex('/tmp/_c2q.dex')
    logs = {i for i, (c, p, n) in enumerate(d.methods) if c == 'Landroid/util/Log;' and n in ('i', 'd')
            and d.mname(i).endswith('(Ljava/lang/String;Ljava/lang/String;)I')}
    n = 0
    for m in d.find('LMC/jwb;', 'CCT_WB'):
        c = Code(d.b, d.code[m]); k = quiet(c, d, logs); check(c)
        struct.pack_into('<%dH' % len(c.w), out, d.code[m] + 16, *c.w); n += k
    out[12:32] = hashlib.sha1(out[32:]).digest(); struct.pack_into('<I', out, 8, zlib.adler32(bytes(out[12:])) & 0xffffffff)
    return bytes(out), n


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.MAXF = MAXF; A.WAIT_ITERS = 1000
    A.EXTRA = pick_extra(d, MAXF - 5); A.SLOT = A.SLOT[:5] + A.EXTRA
    A.extra_methods(d, new); K.key40_methods(d, new); C.metadata_guards(d, new); D.d_methods(d, new)
    P.p152_methods(d, new); I.iso_cap(d, new); Q.probe_gate(d, new)
    print('log calls silenced:', speed(d, new))
    c1 = B.finalize_classes(raw1, d, new)
    c2, n2 = quiet_classes2(B.patch_classes2(z.read('classes2.dex'))); print('classes2 log calls silenced:', n2)
    open('classes.dex.p153', 'wb').write(c1); open('classes2.dex.p153', 'wb').write(c2)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('slots:', len(A.SLOT), 'classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
