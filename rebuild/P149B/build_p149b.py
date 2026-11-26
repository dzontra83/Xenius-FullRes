#!/usr/bin/env python3
"""XENIUS P149B — RES button = 12 MP (OFF) / 50 MP FullRes (ON), with the 12 MP GCam engine restored.

Why P149A was not enough: K13 forces 8192x6144 into Lohv.q, the StaticMetadata builder for the MAIN GCam engine
(Ldvm.j), and every shot (12 or 50 MP) goes through that engine (Ldvm.s). The engine is created once per process,
so RES must (a) restore the original Lohv.q sizes when OFF and (b) restart the app so the engine is rebuilt.

classes.dex (K13 SHA-256 840d6355...)
  A  Llel.c   RES OFF: no RAW50 ImageReader, drop stale RAW50 state                         (as P149A)
  B  Llfe.e   RES OFF: same                                                                 (as P149A)
  C  AeShotParams.j/.k: upscale target never applied                                        (as P149A)
  D  Lohv.q   6 sites: RES OFF -> original code (getcustomwidth/height, Lkre.a/.b); ON -> K13 8192/6144
classes2.dex
  E  getC2apiPref acquire (null arg): RES OFF -> release path (sets key40=0 only if it is not already 0)
  F  getC2apiPref release: skip the setValue(40,0)+200 ms when key40 already reads 0
  G  RES button (Upscale$1.onCheckedChanged): CameraActivity.ReInit() -> LMC/main.onRestart() (app relaunch)
"""
import sys, struct, zipfile, hashlib, zlib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import Asm, one, mid, sid, drop_raw50_state, rebuild_apk, K13_DEX_SHA


def fix_hdr(out):
    out[12:32] = hashlib.sha1(out[32:]).digest()
    struct.pack_into('<I', out, 8, zlib.adler32(bytes(out[12:])) & 0xffffffff)


def collect_classes(raw):
    assert hashlib.sha256(raw).hexdigest() == K13_DEX_SHA, 'classes.dex is not the K13 checkpoint'
    open('/tmp/_c1.dex', 'wb').write(raw); d = Dex('/tmp/_c1.dex')
    ids = dict(getProperties=mid(d, 'Ljava/lang/System;', 'getProperties', ')Ljava/util/Properties;'),
               remove=mid(d, 'Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               close=mid(d, 'Landroid/media/ImageReader;', 'close', '()V'),
               logi=mid(d, 'Landroid/util/Log;', 'i', '(Ljava/lang/String;Ljava/lang/String;)I'),
               menu=mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I'),
               ImageReader=d.types.index('Landroid/media/ImageReader;'))
    fld_c = [i for i, f in enumerate(d.fields) if f == ('Lljq;', 'Ljava/util/concurrent/Executor;', 'c')][0]
    cw = mid(d, 'LMC/main;', 'getcustomwidth', '(I)I'); ch = mid(d, 'LMC/main;', 'getcustomheight', '(I)I')
    kre_a = d.fields.index(('Lkre;', 'I', 'a')); kre_b = d.fields.index(('Lkre;', 'I', 'b'))
    s_res = sid(d, 'pref_upscale_key')
    new = {}

    # A: Llel.c
    m = one(d, 'Llel;', 'c'); c = Code(d.b, d.code[m])
    assert c.w[12] == 0x0029 and c.w[13] == 52 and c.w[14] == 0x0422
    assert c.w[134:136] == [0x7354, fld_c]
    def blkA(p, na):
        a = Asm(p)
        a.const_string(13, s_res); a.inv_static(ids['menu'], [13]); a.move_result(13)
        a.if_nez(13, na(12))
        drop_raw50_state(a, d, 12, 13, ids)
        a.iget_obj(3, 7, fld_c); a.goto32(na(14))
        return a.done()
    insert(c, 12, blkA); check(c); new[m] = c

    # B: Llfe.e
    m = one(d, 'Llfe;', 'e'); c = Code(d.b, d.code[m])
    assert c.w[44] == 0x0513 and c.w[45] == 8192
    def blkB(p, na):
        a = Asm(p)
        a.const_string(5, s_res); a.inv_static(ids['menu'], [5]); a.move_result(5)
        a.if_nez(5, na(44))
        drop_raw50_state(a, d, 6, 7, ids)
        a.ret_obj(0)
        return a.done()
    insert(c, 44, blkB); check(c); new[m] = c

    # D: Lohv.q — (pc, K13 words, original words). Original code from P101 disassembly of the pre-FullRes method.
    m = one(d, 'Lohv;', 'q'); c = Code(d.b, d.code[m])
    sites = [
        (799, [0x0213, 8192, 0, 0], [0x1071, cw, 0x0002, 0x020a]),   # getcustomwidth(v2) -> v2  (pixel array w)
        (816, [0x0013, 6144, 0, 0], [0x1071, ch, 0x0000, 0x000a]),   # getcustomheight(v0) -> v0 (pixel array h)
        (859, [0x0213, 8192, 0, 0], [0x1071, cw, 0x0002, 0x020a]),   # active area right
        (873, [0x0013, 6144, 0, 0], [0x1071, ch, 0x0000, 0x000a]),   # active area bottom
        (894, [0x0213, 8192], [0x2252, kre_a]),                      # iget v2, v2, Lkre;->a  (raw max width)
        (903, [0x0213, 6144], [0x2252, kre_b]),                      # iget v2, v2, Lkre;->b  (raw max height)
    ]
    for p, k13, orig in sites:
        assert c.w[p:p + len(k13)] == k13, ('Lohv.q site changed', p, c.w[p:p + len(k13)])
    for p, k13, orig in sorted(sites, reverse=True):   # high -> low so lower addresses stay valid
        def blkD(base, na, p=p, k13=k13, orig=orig):
            a = Asm(base)
            a.const_string(3, s_res); a.inv_static(ids['menu'], [3]); a.move_result(3)
            a.if_nez(3, na(p))                          # RES ON -> K13 constant
            a.w += orig                                 # RES OFF -> original instruction(s)
            a.goto32(na(p + len(k13)))
            return a.done()
        insert(c, p, blkD)
    check(c); new[m] = c
    return d, new


def finalize_classes(raw, d, new):
    out = bytearray(relocate(raw, {k: v.build() for k, v in new.items()}))

    # C: AeShotParams.j/.k in place
    for n in ('j', 'k'):
        m = one(d, 'Lcom/google/googlex/gcam/AeShotParams;', n); ins = d.code[m] + 16
        w = list(struct.unpack_from('<3H', out, ins + 12))
        assert w == [0x0139, 3, 0x000e], (n, w)
        struct.pack_into('<2H', out, ins + 12, 0, 0)
    fix_hdr(out)
    return bytes(out)


def patch_classes(raw):
    d, new = collect_classes(raw)
    return finalize_classes(raw, d, new)


def patch_classes2(raw):
    open('/tmp/_c2.dex', 'wb').write(raw); d = Dex('/tmp/_c2.dex')
    m = one(d, 'LMC/c2a;', 'getC2apiPref'); c = Code(d.b, d.code[m])
    aem = [i for i, f in enumerate(d.fields) if f[0] == 'LMC/main;' and f[2] == 'Aemodef'][0]
    menu = mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    assert c.w[338:340] == [0x0460, aem]
    assert c.w[349] == 0x0512 and c.w[350] == 0x001a                    # const/4 v5,0 ; const-string v0 (gate start)
    assert c.w[406:410] == [0x0538, 4, 0x0439, 77]                       # if-eqz v5,+4 ; if-nez v4,->485
    assert c.w[485] == 0x0d11                                            # return-object v13
    # F (higher address first): release path skips the write when key40 is already 0
    def blkF(p, na):
        a = Asm(p)
        a.if_nez(5, na(406))     # acquire path -> original logic
        a.if_nez(4, na(406))     # release and key40 != 0 -> original write (goes to 410)
        a.goto32(na(485))        # release and key40 == 0 -> nothing to do
        return a.done()
    insert(c, 406, blkF)
    # E: acquire path with RES OFF -> run the release path instead
    def blkE(p, na):
        a = Asm(p)
        a.const_string(4, sid(d, 'pref_upscale_key')); a.inv_static(menu, [4]); a.move_result(4)
        a.if_nez(4, na(338))     # RES ON -> original acquire
        a.w += [0x0512]          # const/4 v5, 0  (release mode)
        a.goto32(na(350))
        return a.done()
    insert(c, 338, blkE); check(c)
    out = bytearray(relocate(raw, {m: c.build()}))

    # G: RES toggle restarts the app (same helper PRO/LDR/LUT buttons use)
    mu = one(d, 'LMC/UI/Button/Upscale$1;', 'onCheckedChanged'); ins = d.code[mu] + 16
    reinit = mid(d, 'Lcom/google/android/apps/camera/legacy/app/activity/main/CameraActivity;', 'ReInit', '()V')
    restart = mid(d, 'LMC/main;', 'onRestart', '()V')
    w = list(struct.unpack_from('<4H', out, ins + 25 * 2))
    assert w == [0x0071, reinit, 0, 0x000e], w
    struct.pack_into('<H', out, ins + 26 * 2, restart)
    fix_hdr(out)
    return bytes(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src)
    c1 = patch_classes(z.read('classes.dex')); c2 = patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p149b', 'wb').write(c1); open('classes2.dex.p149b', 'wb').write(c2)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
    print('classes2.dex', len(c2), hashlib.sha256(c2).hexdigest())
