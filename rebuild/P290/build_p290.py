#!/usr/bin/env python3
"""XENIUS P175 — 200 MP -> 50 MP binned stream on 35 mm (ID3) and 85 mm (ID5), switched by the Leica button. On P174B.

Same full-size gate (key40) as 50 MP; per RawR's vivo_x300_ultra.json F35/F85 routes the 200 MP mode needs
ultra_highresolution=1 (ai_highresolution off) and isUpscale=1, RAW16 16320x12256 (ID3) / 16320x12288 (ID5),
merge limit 3 frames. Each 200 MP frame is binned to 50 MP (same-colour 2x bin, RawR BayerBin.h kernel) by
libtbin.so before HDR+ sees it, padded to the 8192x6144 the 50 MP engine is built for.

classes2.dex
  K  LMC/UI/Button/Leica: pref 'pref_shading_mode_key' -> 'setTemporalBinning' (0 = 50 MP, 1 = 200->50 MP)
classes.dex
  C  Llel.e entry: props['LiveTemporalBinning'] = CameraDevice (camera id for Llfe.e)
  R1 Llel.c / R2 Llfe.e (RES ON reader): Leica ON and camera '3'/'5' -> reader 16320x(12256|12288), maxImages 6,
     props['TemporalBinning'] set (= 200 MP session flag); flag removed at every session build otherwise
  Q  Laue.a (every request): flag -> ai_highresolution 0, ultra_highresolution 1
  B  Llei.onCaptureCompleted (50 MP burst): flag -> ai 0, ultra 1, isUpscale 1; frame count <= 3
  W  Lleu.onImageAvailable / Ldvm.p: 16320-wide frames pass the 8192 width checks
  E  Llet.<init>: 16320-wide RAW16 -> TemporalBinning.a(image) (classes3.dex, by reflection) -> binned plane list,
     width/height 8192x6144; any failure keeps the original frame
  F  Llet.f(): binned frame -> no HardwareBuffer (GCam reads the binned plane)
classes3.dex (new): TemporalBinning helper (see dexgen.py); lib/arm64-v8a/libtbin.so (tbin.c)
"""
import sys, os, zipfile, hashlib, struct, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dex import Dex
from dexpatch import Code, insert, check, relocate, walk
from build_p149a import one, mid, sid
from build_p149b import fix_hdr
from build_p163 import S
import dexgen

MAXF200 = int(os.environ.get('MAXF200', '3'))
NO200 = os.environ.get('NO200', '1') == '1'
REM3 = NO200 and os.environ.get('REM3', '1') == '1'   # Leica button cycles XR (own remosaic) -> ER (Ed Detail) -> SR (stock)
LOG = os.environ.get('TBLOG', '0') == '1'
P174B_DEX = '00043e10e55737b378257c1668415ac86dcfcdf151a10845e0294f8cc18cf1d8'


def fix_outs(c):
    mx = c.outs
    for pc, op, ln in iter_insns(c.w):
        if op in range(0x6e, 0x73) or op == 0x24: mx = max(mx, c.w[pc] >> 12)
        elif op in range(0x74, 0x79) or op == 0x25: mx = max(mx, c.w[pc] >> 8)
    c.outs = mx


def iter_insns(w):
    for pc, ln, pay in walk(w):
        if not pay: yield pc, w[pc] & 0xff, ln


def find(c, pat, start=0, n=1):
    r = [i for i in range(start, len(c.w) - len(pat) + 1) if all(p is None or c.w[i + k] == p for k, p in enumerate(pat))]
    assert len(r) == n, (pat, r); return r


def patch_classes(raw):
    assert hashlib.sha256(raw).hexdigest() == P174B_DEX, 'classes.dex is not P174B'
    open('/tmp/_p175.dex', 'wb').write(raw); d = Dex('/tmp/_p175.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    T = lambda t: d.types.index(t)
    F = lambda f: d.fields.index(f) if False else [i for i in range(len(d.fields)) if d.fname(i) == f][0]
    props = M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    get = M('Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    put = M('Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    rem = M('Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;')
    menu = M('LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    getid = M('Landroid/hardware/camera2/CameraDevice;', 'getId', '()Ljava/lang/String;')
    seq = M('Ljava/lang/String;', 'equals', '(Ljava/lang/Object;)Z')
    forname = M('Ljava/lang/Class;', 'forName', '(Ljava/lang/String;)Ljava/lang/Class;')
    gdm = M('Ljava/lang/Class;', 'getDeclaredMethods', '()[Ljava/lang/reflect/Method;')
    minv = M('Ljava/lang/reflect/Method;', 'invoke', '(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;')
    imgw = M('Landroid/media/Image;', 'getWidth', '()I')
    KFLAG = sid(d, 'TemporalBinning'); KCAM = sid(d, 'LiveTemporalBinning'); KPREF = sid(d, 'setTemporalBinning')
    S3, S5 = sid(d, '3'), sid(d, '5')
    KDIM = sid(d, 'getWidth')                   # P290: props key, frame size of the converted frame
    KQUAD = sid(d, 'quadTo')                    # props marker: native quad 50 MP on the main camera (RES on, Leica off)
    QUAD = os.environ.get('NOQUAD') != '1'
    def kpref(a, r):          # Leica button: 200 MP (NO200=0) or remosaic compare (default; 200 MP never starts)
        if NO200: a.c4(r, 0)
        else: a.cs(r, KPREF); a.inv(0x71, menu, [r]); a.mr(r)
    out = {}

    def flag_block(a, rp, rk, lbl_end):
        """rk = props.get(FLAG) ; if-eqz rk -> lbl_end   (rp, rk temps)"""
        a.inv(0x71, props, []); a.mro(rp); a.cs(rk, KFLAG); a.inv(0x72, get, [rp, rk]); a.mro(rk)
        a.b21(0x38, rk, lbl_end)

    def reader_block(a, rp, rt, ru, dev_from, wreg, hreg, nreg):
        """size selection; rp/rt/ru temps; dev_from(a, reg) loads the CameraDevice (or leaves null -> end)."""
        a.inv(0x71, props, []); a.mro(rp)
        a.cs(rt, KFLAG); a.inv(0x72, rem, [rp, rt])
        kpref(a, rt); a.b21(0x38, rt, 'end')
        dev_from(a, rt); a.b21(0x38, rt, 'end')
        a.inv(0x6e, getid, [rt]); a.mro(rt)
        a.cs(ru, S3); a.inv(0x6e, seq, [ru, rt]); a.mr(ru); a.b21(0x39, ru, 'main')
        a.cs(ru, S5); a.inv(0x6e, seq, [ru, rt]); a.mr(ru); a.b21(0x38, ru, 'end')
        a.c16(hreg, 12288); a.go('set')
        a.L('main'); a.c16(hreg, 12256)
        a.L('set'); a.c16(wreg, 16320); a.c4(nreg, 6)
        a.cs(rt, KFLAG); a.inv(0x72, put, [rp, rt, rt])
        a.L('end')

    # ---- LOG: helper(o) by reflection; tries -> catch-all continues ----
    def helper_call(c, p, rm, rarr, rarg, rrecv=None):
        """insert before p: TemporalBinning.a(rarg) (rm, rarr temps; receiver = rarg)."""
        info = {}
        def blk(base, na):
            a = S(base); a.L('t0')
            a.cs(rm, KFLAG); a.inv(0x71, forname, [rm]); a.mro(rm); a.inv(0x6e, gdm, [rm]); a.mro(rm)
            a.c4(rarr, 0); a.raw(0x46 | rm << 8, rm | rarr << 8)
            a.raw(0x24 | 1 << 12, T('[Ljava/lang/Object;'), rarg); a.mro(rarr)
            a.inv(0x6e, minv, [rm, rarg, rarr])
            a.L('t1'); a.L('h')
            w = a.done(); info.update(t0=a.lab['t0'], t1=a.lab['t1'], h=a.lab['h']); return w
        insert(c, p, blk); check(c)
        new = []
        for t in c.tries:
            st, cnt, h = t; e = st + cnt
            if st < info['t1'] and e > info['t0']:
                if st < info['t0']: new.append([st, info['t0'] - st, h])
                if e > info['t1']: new.append([info['t1'], e - info['t1'], h])
            else: new.append(t)
        c.handlers.append([[], info['h']]); new.append([info['t0'], info['t1'] - info['t0'], len(c.handlers) - 1])
        c.tries = sorted(new, key=lambda t: t[0])

    # ---- C: Llel.e entry records the CameraDevice ----
    m = one(d, 'Llel;', 'e'); c = Code(raw, d.code[m])
    fl = F('Llel;->a:Landroid/hardware/camera2/CameraDevice;')
    assert c.w[0:2] == [0x0654 | 0, fl] or (c.w[0] & 0xff) == 0x54, c.w[:2]
    def C(p, na):
        a = S(p); a.inv(0x71, props, []); a.mro(1); a.cs(2, KCAM); a.inv(0x72, put, [1, 2, 0]); return a.done()
    insert(c, 2, C); check(c); fix_outs(c); out[m] = c.build()

    # ---- R1: Llel.c ----
    m = one(d, 'Llel;', 'c'); c = Code(raw, d.code[m])
    p = find(c, [0x0913, 8192, 0x0a13, 6144, 0x0b13, 32, 0x0c13, 25])[0] + 8 + 3   # after const-wide/32 v13
    assert (c.w[p] & 0xff) == 0x77, hex(c.w[p])
    def dev_llel(a, r):
        a.raw(0x54 | r << 8 | 6 << 12, fl)                                   # iget-object r, v6, Llel.a
    def R1(base, na):
        a = S(base); reader_block(a, 4, 5, 15 if False else 5, dev_llel, 9, 10, 12); return a.done()
    # temps: v4 props, v5 key/id, need a third temp for equals result -> use v15? (only <16 for 35c) -> v15 ok
    def R1(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(4)
        a.cs(5, KFLAG); a.inv(0x72, rem, [4, 5])
        a.cs(5, KQUAD); a.inv(0x72, rem, [4, 5])
        dev_llel(a, 5); a.b21(0x38, 5, 'end')
        a.inv(0x6e, getid, [5]); a.mro(5)
        kpref(a, 15); a.b21(0x38, 15, 'nolei')
        a.cs(15, S3); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x39, 15, 'main')
        a.cs(15, S5); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x39, 15, 'tele')
        a.cs(15, sid(d, '9')); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x38, 15, 'end')
        a.L('tele')
        a.c16(10, 12288); a.go('set')
        a.L('main'); a.c16(10, 12256)
        a.L('set'); a.c16(9, 16320); a.c4(12, 6)
        a.cs(5, KFLAG); a.inv(0x72, put, [4, 5, 5]); a.go('end')
        a.L('nolei')
        if QUAD:
            a.cs(15, S3); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x39, 15, 'qput')
            a.cs(15, S5); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x39, 15, 'qput')     # tele
            if os.environ.get('TC9', '1') == '1':                                         # P290: teleconverter (id 9) = tele quad
                a.cs(15, sid(d, '9')); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x38, 15, 'q9n')
                a.cs(5, S5); a.go('qput')
                a.L('q9n')
            a.inv(0x6e, M('Ljava/lang/String;', 'hashCode', '()I'), [5]); a.mr(15)       # ultra-wide: "4".hashCode() == 52
            a.raw(0xd8 | 15 << 8, 15 | 0xcc << 8); a.b21(0x39, 15, 'end')            # add-int/lit8 -52; if-nez
            a.L('qput'); a.cs(15, KQUAD); a.inv(0x72, put, [4, 15, 5])              # value = camera id
        a.L('end')
        return a.done()
    insert(c, p, R1); check(c)
    # flag removal on every session build (RES OFF path too): before 'pref_upscale_key' MenuValue
    q = find(c, [0x0d1a, sid(d, 'pref_upscale_key')])[0]
    def R1b(base, na):
        a = S(base); a.inv(0x71, props, []); a.mro(12); a.cs(13, KFLAG); a.inv(0x72, rem, [12, 13])
        a.cs(13, KQUAD); a.inv(0x72, rem, [12, 13]); return a.done()
    insert(c, q, R1b); check(c); fix_outs(c); out[m] = c.build()

    # ---- R2: Llfe.e ----
    m = one(d, 'Llfe;', 'e'); c = Code(raw, d.code[m])
    p = find(c, [0x0513, 8192, 0x0613, 6144, 0x0713, 32, 0x0813, 25])[0] + 8 + 3
    assert (c.w[p] & 0xff) == 0x77, hex(c.w[p])
    def R2(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(1)
        a.cs(2, KFLAG); a.inv(0x72, rem, [1, 2])
        a.cs(2, KQUAD); a.inv(0x72, rem, [1, 2])
        a.cs(2, KCAM); a.inv(0x72, get, [1, 2]); a.mro(2); a.b21(0x38, 2, 'end')
        a.raw(0x1f | 2 << 8, T('Landroid/hardware/camera2/CameraDevice;'))
        a.inv(0x6e, getid, [2]); a.mro(2)
        kpref(a, 3); a.b21(0x38, 3, 'nolei')
        a.cs(3, S3); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x39, 3, 'main')
        a.cs(3, S5); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x39, 3, 'tele')
        a.cs(3, sid(d, '9')); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x38, 3, 'end')
        a.L('tele')
        a.c16(6, 12288); a.go('set')
        a.L('main'); a.c16(6, 12256)
        a.L('set'); a.c16(5, 16320); a.c4(8, 6)
        a.cs(2, KFLAG); a.inv(0x72, put, [1, 2, 2]); a.go('end')
        a.L('nolei')
        if QUAD:
            a.cs(3, S3); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x39, 3, 'qput')
            a.cs(3, S5); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x39, 3, 'qput')
            if os.environ.get('TC9', '1') == '1':                                         # P290: teleconverter (id 9) = tele quad
                a.cs(3, sid(d, '9')); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x38, 3, 'q9n')
                a.cs(2, S5); a.go('qput')
                a.L('q9n')
            a.inv(0x6e, M('Ljava/lang/String;', 'hashCode', '()I'), [2]); a.mr(3)
            a.raw(0xd8 | 3 << 8, 3 | 0xcc << 8); a.b21(0x39, 3, 'end')
            a.L('qput'); a.cs(3, KQUAD); a.inv(0x72, put, [1, 3, 2])
        a.L('end')
        return a.done()
    insert(c, p, R2); check(c)
    q = find(c, [0x051a, sid(d, 'pref_upscale_key')])[0]
    def R2b(base, na):
        a = S(base); a.inv(0x71, props, []); a.mro(5); a.cs(6, KFLAG); a.inv(0x72, rem, [5, 6])
        a.cs(6, KQUAD); a.inv(0x72, rem, [5, 6]); return a.done()
    insert(c, q, R2b); check(c); fix_outs(c); out[m] = c.build()

    # ---- Q: Laue.a vendor keys ----
    m = [i for i, (cc, pp, nn) in enumerate(d.methods) if cc == 'Laue;' and nn == 'a' and 'CameraDevice' in d.mname(i)][0]
    c = Code(raw, d.code[m])
    ivo = M('Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    for key, orig, new in (('vivo.control.ai_highresolution', 1, 0), ('vivo.control.ultra_highresolution', 0, 1)):
        k = find(c, [0x011a, sid(d, key)])[0]
        cpos = k + 2 + 2 + 3                                                  # const-string, const-class v4, invoke-direct
        assert c.w[cpos] == (0x12 | 1 << 8 | orig << 12) and c.w[cpos + 1:cpos + 3] == [0x1071, ivo], (key, c.w[cpos:cpos + 3])
        def Qb(base, na, new=new):
            a = S(base); flag_block(a, 4, 4, 'end') if False else None
            a.inv(0x71, props, []); a.mro(4); a.cs(1, KFLAG); a.inv(0x72, get, [4, 1]); a.mro(4)
            a.raw(0x12 | 1 << 8 | (1 - new) << 12)                            # restore original value in v1
            a.b21(0x38, 4, 'end'); a.c4(1, new)
            a.L('end'); return a.done()
        insert(c, cpos + 1, Qb); check(c)
    fix_outs(c); out[m] = c.build()

    # ---- B: Llei vendor keys + frame cap ----
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])
    for key, orig, new in (('vivo.control.ai_highresolution', 1, 0), ('vivo.control.ultra_highresolution', 0, 1),
                           ('vivo.control.isUpscale', 0, 1)):
        k = find(c, [0x021a, sid(d, key)])[0]
        cpos = k + 2 + 2 + 3
        assert c.w[cpos] == (0x12 | 2 << 8 | orig << 12) and c.w[cpos + 1:cpos + 3] == [0x1071, ivo], (key, c.w[cpos:cpos + 3])
        def Bb(base, na, new=new, orig=orig):
            a = S(base)
            a.inv(0x71, props, []); a.mro(6); a.cs(2, KFLAG); a.inv(0x72, get, [6, 2]); a.mro(6)
            a.raw(0x12 | 2 << 8 | orig << 12)
            a.b21(0x38, 6, 'end'); a.c4(2, new)
            a.L('end'); return a.done()
        insert(c, cpos + 1, Bb); check(c)
    HN = sid(d, 'pref_hdrnet_key')
    hb = [i for i in range(len(c.w) - 9) if c.w[i:i + 3] == [0x1071, ivo, 0x0000] and c.w[i + 3] == 0x000c
          and c.w[i + 4:i + 6] == [0x0071, props] and c.w[i + 7] == 0x020c and c.w[i + 8] == 0x041a and c.w[i + 9] == HN]
    assert len(hb) == 1, hb
    def Bc(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(2); a.cs(4, KFLAG); a.inv(0x72, get, [2, 4]); a.mro(4)
        a.b21(0x38, 4, 'end'); a.c4(4, MAXF200); a.b22(0x37, 0, 4, 'end')         # if-le v0, v4
        a.raw(0x0001 | 0 << 8 | 4 << 12)                                     # move v0, v4
        a.L('end'); return a.done()
    insert(c, hb[0], Bc); check(c)
    # Z: 200 MP -> the ZSL frame selector may be 1 (GCam's clamp is 2..20; 1 stays 1, >3 capped by Bc)
    zp = [q for q in range(len(c.w) - 1) if c.w[q] == 0x2212 and c.w[q + 1] == 0x2034 and q < hb[0] and hb[0] - q < 80]
    assert len(zp) == 1, zp
    def Zb(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(4); a.cs(2, KFLAG); a.inv(0x72, get, [4, 2]); a.mro(4)
        a.c4(2, 2); a.b21(0x38, 4, 'end'); a.c4(2, 1)
        a.L('end'); return a.done()
    insert(c, zp[0] + 1, Zb); check(c)
    # ZC: GCam's Pixel device profiles (Lcwx.a / Lcwy.a) set ZSL frames Lcxs.g / Lcxs.h = 5 -> 12 MP ZSL shots
    #     never take more than 5 frames whatever the selector says. Raise the profile value to ZSLCAP (30).
    ZSLCAP = int(os.environ.get('ZSLCAP', '0'))
    if ZSLCAP:
        fG = F('Lcxs;->g:Lcxo;')
        for cls in ('Lcwx;', 'Lcwy;'):
            zm = one(d, cls, 'a'); zc = Code(raw, d.code[zm])
            q = [i for i in range(len(zc.w) - 2) if zc.w[i] & 0xff == 0x62 and zc.w[i + 1] == fG
                 and zc.w[i + 2] & 0xff == 0x12 and zc.w[i + 2] >> 12 == 5]
            assert len(q) == 1, (cls, q)
            rv = (zc.w[q[0] + 2] >> 8) & 15
            def ZC(base, na, rv=rv):
                a = S(base); a.c16(rv, ZSLCAP); return a.done()
            insert(zc, q[0] + 3, ZC); check(zc); fix_outs(zc); out[zm] = zc.build()
    # DG (log builds): Ldvm.G (every HDR+ shot's ShotParams) -> helper dumps Ldvm.l (Ldug, ZSL frame config)
    if LOG:
        gm = one(d, 'Ldvm;', 'G'); gc = Code(raw, d.code[gm])
        assert gc.regs == 27 and gc.ins == 12
        fDl = F('Ldvm;->l:Ldug;')
        def DG(base, na):
            a = S(base); a.raw(0x54 | 14 << 8 | 15 << 12, fDl); return a.done()     # iget-object v14, v15, Ldvm.l
        insert(gc, 0, DG); check(gc)
        helper_call(gc, 2, 12, 13, 14); fix_outs(gc); out[gm] = gc.build()
    # M1 (Llei entry): viewfinder results (Llei.a != null) -> props gains / transform / neutral point
    crget = M('Landroid/hardware/camera2/CaptureResult;', 'get', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;')
    CRK = 'Landroid/hardware/camera2/CaptureResult$Key;'
    fCR = lambda n: [i for i in range(len(d.fields)) if d.fname(i) == 'Landroid/hardware/camera2/CaptureResult;->%s:%s' % (n, CRK)][0]
    KG, KT, KN = sid(d, 'AwbInfo_gains_get'), sid(d, 'AwbInfo_rgb2rgb_get'), sid(d, 'AwbInfo_IsValid')
    fLa = F('Llei;->a:Lldg;')
    KL = sid(d, 'Landroid/hardware/camera2/params/LensShadingMap;')       # props key: viewfinder lens shading map
    m1 = {}
    def M1(base, na):
        a = S(base); a.L('t0')
        a.raw(0x54 | 0 << 8 | 4 << 12, fLa); a.b21(0x38, 0, 'end')
        a.inv(0x71, props, []); a.mro(1)
        for kn, ks in (('COLOR_CORRECTION_GAINS', KG), ('COLOR_CORRECTION_TRANSFORM', KT), ('SENSOR_NEUTRAL_COLOR_POINT', KN),
                       ('SENSOR_SENSITIVITY', sid(d, 'ISOSpeedLatitudezzz')),
                       ('SENSOR_EXPOSURE_TIME', sid(d, 'ExposureTime')),      # P290: viewfinder exposure (night key)
                       ('STATISTICS_LENS_SHADING_CORRECTION_MAP', KL),
                       ('SCALER_CROP_REGION', sid(d, 'Landroid/graphics/Rect;')),
                       ('LENS_FOCUS_DISTANCE', sid(d, 'CdrSCFocus'))):            # quad UW QSC: focus-dependent table
            a.raw(0x62, fCR(kn)); a.inv(0x6e, crget, [7, 0]); a.mro(2); a.b21(0x38, 2, 'n' + kn)
            a.cs(3, ks); a.inv(0x72, put, [1, 3, 2])
            a.L('n' + kn)
        if os.environ.get('PVW', '0') == '1':                 # PVW: the viewfinder request (p2 = v6), key = CaptureRequest.class
            a.raw(0x1c | 3 << 8, T('Landroid/hardware/camera2/CaptureRequest;')); a.inv(0x72, put, [1, 3, 6])
        a.L('t1'); a.L('end')
        w = a.done(); m1.update(t0=a.lab['t0'], t1=a.lab['t1'], h=a.lab['end']); return w
    insert(c, 0, M1); check(c)
    c.handlers.append([[], m1['h']]); c.tries.append([m1['t0'], m1['t1'] - m1['t0'], len(c.handlers) - 1])
    c.tries.sort(key=lambda t: t[0])
    if LOG: helper_call(c, 0, 2, 3, 7)                    # AF trace: every result of this callback -> helper
    # L1: log the final burst count: after 'invoke-static {v0} Integer.valueOf; move-result-object v0'
    q = find(c, [0x1071, ivo, 0x0000, 0x000c, 0x0071, props])[0] + 4
    if LOG: helper_call(c, q, 2, 4, 0)
    # Q1: 200 MP -> one capture now, the rest one-by-one from Lleu (helper queue). Before 'Integer.intValue' of the count.
    q = find(c, [0x106e, M('Ljava/lang/Integer;', 'intValue', '()I'), 0x0000, 0x000a, 0x406e, M('Landroid/hardware/camera2/CameraCaptureSession;', 'capture', '(Landroid/hardware/camera2/CaptureRequest;Landroid/hardware/camera2/CameraCaptureSession$CaptureCallback;Landroid/os/Handler;)I')])[0]
    qi = {}
    def Q1(base, na):
        a = S(base); a.L('t0')
        a.raw(0x24 | 5 << 12 | 0 << 8, T('[Ljava/lang/Object;'), 5 | 7 << 4 | 1 << 8 | 3 << 12); a.mro(4)   # {v5,v7,v1,v3,v0}
        a.cs(2, KFLAG); a.inv(0x71, forname, [2]); a.mro(2); a.inv(0x6e, gdm, [2]); a.mro(2)
        a.c4(6, 0); a.raw(0x46 | 2 << 8, 2 | 6 << 8)
        a.raw(0x24 | 1 << 12, T('[Ljava/lang/Object;'), 4); a.mro(6)
        a.inv(0x6e, minv, [2, 4, 6]); a.mro(2)
        a.b21(0x38, 2, 't1'); a.raw(0x1f | 2 << 8, T('Ljava/lang/Integer;')); a.raw(0x07 | 0 << 8 | 2 << 12)  # v0 = Integer(1)
        a.L('t1'); a.L('h')
        w = a.done(); qi.update(t0=a.lab['t0'], t1=a.lab['t1'], h=a.lab['h']); return w
    insert(c, q, Q1); check(c)
    new = []
    for t in c.tries:
        st, cnt, h = t; e = st + cnt
        if st < qi['t1'] and e > qi['t0']:
            if st < qi['t0']: new.append([st, qi['t0'] - st, h])
            if e > qi['t1']: new.append([qi['t1'], e - qi['t1'], h])
        else: new.append(t)
    c.handlers.append([[], qi['h']]); new.append([qi['t0'], qi['t1'] - qi['t0'], len(c.handlers) - 1])
    c.tries = sorted(new, key=lambda t: t[0])
    # QB: quad 50 MP main, the RES still burst (sent after abortCaptures): request builder v7 -> helper sets
    #     vivo.control.forceSensorMode {3} when props 'quadTo'; the viewfinder session keeps the remosaiced mode
    if QUAD:
        bld = M('Landroid/hardware/camera2/CaptureRequest$Builder;', 'build', '()Landroid/hardware/camera2/CaptureRequest;')
        q = find(c, [0x106e, bld, 0x0007, 0x070c])
        assert len(q) == 1, q
        helper_call(c, q[0], 0, 1, 7)
    fix_outs(c); out[m] = c.build()

    # L2: Llei.onCaptureFailed (burst callback): log the CaptureFailure (v4)
    m = one(d, 'Llei;', 'onCaptureFailed'); c = Code(raw, d.code[m])
    q = find(c, [0x106e, M('Landroid/hardware/camera2/CaptureFailure;', 'getReason', '()I'), 0x0004])[0]
    if LOG:
        helper_call(c, q, 0, 2, 4)
    # RT: RES burst frame failed (Llei.a == null path, ends 'move-result v0; return-void'): helper resends the request once
    if os.environ.get('NORETRY') != '1':
        rp = [i for i in range(len(c.w) - 1) if c.w[i] == 0x0013 and c.w[i + 1] == 72]   # 'const/16 v0, 72': a == null path
        assert len(rp) == 1, rp                                                  # (before the logs reuse v2 = session)
        def RT(base, na):
            a = S(base)
            a.raw(0x24 | 3 << 12, T('[Ljava/lang/Object;'), 2 | 3 << 4 | 1 << 8); a.mro(0)   # {session, request, this}
            return a.done()
        insert(c, rp[0], RT); check(c)
        helper_call(c, rp[0] + 4, 2, 3, 0)                                   # temps v2, v3 (in the array); v4 kept
    fix_outs(c); out[m] = c.build()

    # ---- AFR: Lkxc.p(Key, Object) builds every request key/value pair. For CONTROL_AF_REGIONS the helper swaps GCam's
    #      empty region (0,0,0,0, weight 0: "camera decides" -> the vivo HAL hops its own small AF windows and the lens
    #      keeps re-adjusting) for a centre region of the current crop with weight 1000. Tap regions (weight > 0) unchanged.
    if os.environ.get('NOAFR') != '1':
        m = one(d, 'Lkxc;', 'p'); c = Code(raw, d.code[m])
        assert c.regs == 3 and c.ins == 2 and len(c.w) == 6, (c.regs, c.ins, c.w)
        fAFR = [i for i in range(len(d.fields)) if d.fname(i) == 'Landroid/hardware/camera2/CaptureRequest;->CONTROL_AF_REGIONS:Landroid/hardware/camera2/CaptureRequest$Key;'][0]
        tKWS = T('Lkws;'); kinit = M('Lkws;', '<init>', '(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V')
        a = S(0)
        a.raw(0x62 | 0 << 8, fAFR); a.b22(0x33, 4, 0, 'make')              # if key != CONTROL_AF_REGIONS -> make
        a.L('t0')
        a.cs(1, KFLAG); a.inv(0x71, forname, [1]); a.mro(1); a.inv(0x6e, gdm, [1]); a.mro(1)
        a.c4(2, 0); a.raw(0x46 | 1 << 8, 1 | 2 << 8)
        a.raw(0x24 | 1 << 12, T('[Ljava/lang/Object;'), 5); a.mro(2)
        a.inv(0x6e, minv, [1, 5, 2]); a.mro(1)
        a.b21(0x38, 1, 't1'); a.raw(0x07 | 5 << 8 | 1 << 12)               # non-null -> value = result
        a.L('t1'); a.L('make')
        a.raw(0x22 | 0 << 8, tKWS); a.inv(0x70, kinit, [0, 4, 5]); a.raw(0x11 | 0 << 8)
        w = a.done()
        c.regs, c.ins, c.w, c.debug = 6, 2, w, 0
        c.tries = [[a.lab['t0'], a.lab['t1'] - a.lab['t0'], 0]]; c.handlers = [[[], a.lab['make']]]
        fix_outs(c); out[m] = c.build()

    # ---- H: Llel.h (GCam request builder, also session parameters): 200 MP vendor keys ----
    m = one(d, 'Llel;', 'h'); c = Code(raw, d.code[m])
    p = find(c, [0x1071, M('Ljava/lang/Integer;', 'toString', '(I)Ljava/lang/String;'), 0x0007, 0x040c])[0]
    tKey = T('Landroid/hardware/camera2/CaptureRequest$Key;'); tInt = T('Ljava/lang/Integer;')
    kinit = M('Landroid/hardware/camera2/CaptureRequest$Key;', '<init>', '(Ljava/lang/String;Ljava/lang/Class;)V')
    bset = M('Landroid/hardware/camera2/CaptureRequest$Builder;', 'set', '(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V')
    KEYS = [('vivo.control.ultra_highresolution', 1), ('vivo.control.ai_highresolution', 0), ('vivo.control.is_ProRaw_on', 2),
            ('vivo.control.echo.mode', 2), ('vivo.control.scenery.subfunction', 5), ('vivo.control.session.uiSwitch_state', 2)]
    hinfo = {}
    def Hb(base, na):
        a = S(base)
        kpref(a, 2); a.b21(0x38, 2, 'quad')
        a.cs(2, sid(d, 'pref_upscale_key')); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'end')
        a.inv(0x6e, getid, [1]); a.mro(4)
        a.cs(2, S3); a.inv(0x6e, seq, [2, 4]); a.mr(2); a.b21(0x39, 2, 'set')
        a.cs(2, S5); a.inv(0x6e, seq, [2, 4]); a.mr(2); a.b21(0x39, 2, 'set')
        a.cs(2, sid(d, '9')); a.inv(0x6e, seq, [2, 4]); a.mr(2); a.b21(0x38, 2, 'end')
        a.L('set')
        for k, v in KEYS:
            a.raw(0x22 | 4 << 8, tKey); a.cs(2, sid(d, k)); a.raw(0x1c | 5 << 8, tInt)   # const-class v5, Integer
            a.inv(0x70, kinit, [4, 2, 5]); a.c4(2, v); a.inv(0x71, ivo, [2]); a.mro(2)
            a.inv(0x6e, bset, [3, 4, 2])
        a.go('t1')
        a.L('quad')
        if QUAD and os.environ.get('QSESSION') == '1':     # P181: forced mode on the session = black viewfinder
            a.cs(2, sid(d, 'pref_upscale_key')); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 't1')
            a.inv(0x6e, getid, [1]); a.mro(4)
            a.cs(2, S3); a.inv(0x6e, seq, [2, 4]); a.mr(2); a.b21(0x38, 2, 't1')
            a.cs(4, KFLAG); a.inv(0x71, forname, [4]); a.mro(4); a.inv(0x6e, gdm, [4]); a.mro(4)
            a.c4(5, 0); a.raw(0x46 | 4 << 8, 4 | 5 << 8)
            a.raw(0x24 | 1 << 12, T('[Ljava/lang/Object;'), 3); a.mro(5)
            a.inv(0x6e, minv, [4, 3, 5])
        a.L('t1')
        a.L('end')
        w = a.done(); hinfo['t0'] = a.lab['set']; hinfo['t1'] = a.lab['t1']; hinfo['end'] = a.lab['end']; return w
    insert(c, p, Hb); check(c)
    for s_, n_, h_ in c.tries: assert s_ + n_ <= hinfo['t0'] or s_ >= hinfo['t1'], 'try overlap H'
    c.handlers.append([[], hinfo['end']]); c.tries.append([hinfo['t0'], hinfo['t1'] - hinfo['t0'], len(c.handlers) - 1])
    c.tries.sort(key=lambda t: t[0]); fix_outs(c); out[m] = c.build()

    # ---- SET (P239): Llei.onCaptureSequenceCompleted (burst callback) -> helper(session) right before it restarts the
    #      viewfinder request; after the last 50 MP frame the helper holds the viewfinder SETTLE ms (see dexgen) ----
    if int(os.environ.get('SETTLE', '300')) > 0:
        m = one(d, 'Llei;', 'onCaptureSequenceCompleted'); c = Code(raw, d.code[m])
        srr = M('Landroid/hardware/camera2/CameraCaptureSession;', 'setRepeatingRequest', '(Landroid/hardware/camera2/CaptureRequest;Landroid/hardware/camera2/CameraCaptureSession$CaptureCallback;Landroid/os/Handler;)I')
        q = find(c, [0x406e, srr, 10 | 2 << 4 | 3 << 8 | 0 << 12])            # {v10 session, v2 request, v3 cb, v0 handler}
        assert c.regs == 14, c.regs
        helper_call(c, q[0], 4, 5, 10)                                       # temps v4, v5 (free here)
        fix_outs(c); out[m] = c.build()
    # ---- M2: Lohv.h (AwbInfo) / M3: Lohv.k (black level): 200 MP flag -> viewfinder values / static black ----
    m = one(d, 'Lohv;', 'h'); c = Code(raw, d.code[m])
    tRV = T('Landroid/hardware/camera2/params/RggbChannelVector;'); tCST = T('Landroid/hardware/camera2/params/ColorSpaceTransform;')
    tRA = T('[Landroid/util/Rational;')
    def subst(c, p, rp, rv, dst, key, typ):
        def blk(base, na):
            a = S(base)
            a.inv(0x71, props, []); a.mro(rp); a.cs(rv, KFLAG); a.inv(0x72, get, [rp, rv]); a.mro(rv); a.b21(0x38, rv, 'end')
            a.cs(rv, key); a.inv(0x72, get, [rp, rv]); a.mro(rv); a.b21(0x38, rv, 'end')
            a.raw(0x1f | rv << 8, typ); a.raw(0x07 | dst << 8 | rv << 12)      # check-cast ; move-object dst, rv
            a.L('end'); return a.done()
        insert(c, p, blk); check(c)
    # neutral point at entry: after 'move-result-object v3' (pc 5)
    assert c.w[5] == 0x030c; subst(c, 6, 0, 1, 3, KN, tRA)
    p = find(c, [0x041f, tRV, 0x0439])[0] + 2; subst(c, p, 5, 6, 4, KG, tRV)       # before if-nez v4 (gains)
    p = find(c, [0x061f, tCST, 0x0639])[0] + 2; subst(c, p, 1, 2, 6, KT, tCST)     # before if-nez v6 (transform)
    # (fix-awbgains path not patched: its 10t goto back to pc 122 would overflow)
    fix_outs(c); out[m] = c.build()
    # ---- S: Lohv.n (SpatialGainMap): 200 MP results report SHADING_MODE OFF (identity map) -> viewfinder map ----
    m = one(d, 'Lohv;', 'n'); c = Code(raw, d.code[m])
    tLSM = T('Landroid/hardware/camera2/params/LensShadingMap;')
    assert c.w[14] == (0x1f | 0 << 8) and c.w[15] == tLSM and (c.w[16] & 0xff) == 0x39, c.w[14:17]
    if os.environ.get('VFLSC') == '1':                                    # P178 experiment, off: the 200 MP map is real
        subst(c, 16, 2, 3, 0, KL, tLSM)
        fix_outs(c); out[m] = c.build()
    m = one(d, 'Lohv;', 'k'); c = Code(raw, d.code[m])
    p = [q for q in find(c, [0x031f, T('[F'), 0x0338], n=3) if c.w[q - 6:q - 4] == [0x0362, fCR('SENSOR_DYNAMIC_BLACK_LEVEL')]]
    assert len(p) == 1, p
    p = p[0] + 2
    def M3(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(4); a.cs(5, KFLAG); a.inv(0x72, get, [4, 5]); a.mro(4); a.b21(0x38, 4, 'end')
        a.c4(3, 0); a.L('end'); return a.done()
    insert(c, p, M3); check(c)
    if os.environ.get('NZFIX', '1') == '1':
        # 50 MP noise model: ohv.k builds GCam's NoiseModel from SENSOR_NOISE_PROFILE (or the port's custom model);
        # right after that choice: v3 = ((Map) Class.forName("action").newInstance()).put(v3, v14 result) -> Laction.put
        # rescales it for quad (RES) captures (measured: real S ~0.2x, O ~0.05x of what the HAL reports)
        # hook right after v3 = result.get(SENSOR_NOISE_PROFILE): the port's selector / custom model later replace v3
        # untouched, so only the stock (HAL) profile gets corrected
        tpair = d.types.index('[Landroid/util/Pair;'); p = None
        fnp = fCR('SENSOR_NOISE_PROFILE')
        for k in range(len(c.w) - 5):
            if c.w[k] == (0x62 | 3 << 8) and c.w[k + 1] == fnp and c.w[k + 2] & 0xff == 0x72 and c.w[k + 5] == (0x0c | 3 << 8):
                p = k + 6; break
        assert p is not None
        fnm = mid(d, 'Ljava/lang/Class;', 'forName', '(Ljava/lang/String;)Ljava/lang/Class;')
        nim = mid(d, 'Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;')
        mpu = mid(d, 'Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
        tmap = d.types.index('Ljava/util/Map;'); sac = d.strings.index('action')
        def NZ(base, na):
            a = S(base)
            a.cs(4, sac); a.inv(0x71, fnm, [4]); a.mro(4); a.inv(0x6e, nim, [4]); a.mro(4)
            a.raw(0x1f | 4 << 8, tmap); a.inv(0x72, mpu, [4, 3, 14]); a.mro(3)
            return a.done()
        insert(c, p, NZ); check(c)
    # ---- P290: cap GCam's HDR ratio (long/short exposure) -> less local shadow lift, more global, natural tone ----
    hcap = float(os.environ.get('HDRCAP', '1.5'))
    if hcap > 0:
        LH = 'Lcom/google/googlex/gcam/LiveHdrMetadata;'
        lhi = M(LH, '<init>', '(JZ)V'); fla = [i for i, f in enumerate(d.fields) if f == (LH, 'J', 'a')][0]
        mset = M('Lcom/google/googlex/gcam/GcamModuleJNI;', 'LiveHdrMetadata_max_hdr_ratio_override_set', '(J' + LH + 'F)V')
        ks = [k for k, _, pl in walk(c.w) if not pl and c.w[k] & 0xff == 0x70 and c.w[k + 1] == lhi]
        assert len(ks) == 1 and c.w[ks[0]] == 0x4070 and c.w[ks[0] + 2] == 0x5438, [hex(x) for x in c.w[ks[0]:ks[0] + 3]]
        fb = struct.unpack('<I', struct.pack('<f', hcap))[0]
        def HC(base, na):
            a = S(base)
            a.raw(0x53 | 3 << 8 | 8 << 12, fla)                                   # iget-wide v3, v8, a
            a.raw(0x14 | 5 << 8, fb & 0xffff, fb >> 16)                           # const v5, cap
            a.inv(0x71, mset, [3, 4, 8, 5]); a.c4(5, 1)                          # restore v5 = 1 (used next)
            return a.done()
        insert(c, ks[0] + 3, HC); check(c)
        print('P290 HDR ratio cap', hcap)
    fix_outs(c); out[m] = c.build()

    # ---- P290: RawR-like night key. AeShotParams.g(F) = GCam's shot exposure compensation (slider EV, shot time only):
    #      ev' = helper.compare(Float ev) / 1000, the helper adds a darkening that grows as the viewfinder scene gets
    #      darker (EV100 from props ISO + exposure). Viewfinder unchanged. NIGHTKEY=0 -> off ----
    if float(os.environ.get('NIGHTKEY', '1.7')) > 0:
        AESP = 'Lcom/google/googlex/gcam/AeShotParams;'
        m = one(d, AESP, 'g'); c = Code(raw, d.code[m])
        assert c.regs == 4 and c.ins == 2 and len(c.w) == 6, (c.regs, c.ins, [hex(x) for x in c.w])
        fa, eset = c.w[1], c.w[3]
        fvo = M('Ljava/lang/Float;', 'valueOf', '(F)Ljava/lang/Float;')
        a = S(0); a.L('t0')
        a.cs(0, sid(d, 'getWidth')); a.inv(0x71, forname, [0]); a.mro(0)
        a.inv(0x6e, M('Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;'), [0]); a.mro(0)
        a.raw(0x1f | 0 << 8, T('Ljava/util/Comparator;'))
        a.inv(0x71, fvo, [7]); a.mro(1); a.c4(2, 0)
        a.inv(0x72, M('Ljava/util/Comparator;', 'compare', '(Ljava/lang/Object;Ljava/lang/Object;)I'), [0, 1, 2]); a.mr(3)
        k1000 = struct.unpack('<I', struct.pack('<f', 1000.0))[0]
        a.raw(0x82 | 3 << 8 | 3 << 12); a.raw(0x14 | 4 << 8, k1000 & 0xffff, k1000 >> 16)
        a.raw(0xc9 | 3 << 8 | 4 << 12); a.raw(0x01 | 7 << 8 | 3 << 12)               # v7 = ev'
        a.L('t1')
        a.L('h'); a.raw(0x53 | 0 << 8 | 6 << 12, fa); a.inv(0x71, eset, [0, 1, 6, 7]); a.raw(0x000e)
        c.w = a.done(); c.regs = 8
        c.tries = [[a.lab['t0'], a.lab['t1'] - a.lab['t0'], 0]]; c.handlers = [[[], a.lab['h']]]
        check(c); fix_outs(c); out[m] = c.build()
        print('P290 night key', os.environ.get('NIGHTKEY', '1.7'))

    # ---- W1: Lleu reader width check ----
    m = one(d, 'Lleu;', 'onImageAvailable'); c = Code(raw, d.code[m])
    p = find(c, [0x0313, 8192, 0x3233])[0]
    tOA = T('[Ljava/lang/Object;'); winfo = {}
    def W1(base, na):
        a = S(base); a.c16(3, 16320); a.b22(0x32, 2, 3, 'go')
        a.c16(3, 8192); a.b22(0x33, 2, 3, 'end')         # P227: 50 MP frames too -> helper sends the next paced capture
        a.L('go'); a.L('t0')
        a.cs(3, KFLAG); a.inv(0x71, forname, [3]); a.mro(3); a.inv(0x6e, gdm, [3]); a.mro(3)
        a.c4(4, 0); a.raw(0x46 | 3 << 8, 3 | 4 << 8)                        # aget-object v3, v3, v4
        a.cs(4, sid(d, 'RAW50_REQ')); a.raw(0x24 | 1 << 12, tOA, 4); a.mro(4)
        a.c4(5, 0); a.inv(0x6e, minv, [3, 5, 4]); a.mro(3)
        a.L('t1')
        a.L('set'); a.c16(2, 8192); a.L('end')
        w = a.done(); winfo.update(t0=a.lab['t0'], t1=a.lab['t1'], h=a.lab['set']); return w
    insert(c, p, W1); check(c)
    for s_, n_, h_ in c.tries: assert s_ + n_ <= winfo['t0'] or s_ >= winfo['t1'], 'try overlap W1'
    c.handlers.append([[], winfo['h']]); c.tries.append([winfo['t0'], winfo['t1'] - winfo['t0'], len(c.handlers) - 1])
    c.tries.sort(key=lambda t: t[0]); fix_outs(c); out[m] = c.build()

    # ---- P247: Ldvm.o entry -> helper(Ldxh): register the shot's raw 50 MP frames for the pre-merge ----
    if os.environ.get('MRG', '1') != '0':
        m = one(d, 'Ldvm;', 'o'); c = Code(raw, d.code[m])
        helper_call(c, 0, 0, 1, 8); fix_outs(c); out[m] = c.build()

    # ---- W2: Ldvm.p slot image width check ----
    m = one(d, 'Ldvm;', 'p'); c = Code(raw, d.code[m])
    tI = T('Landroid/media/Image;')
    p = find(c, [0x021f, tI, 0x106e, imgw, 0x0002, 0x010a, 0x0013, 8192, 0x0133])[0] + 6
    def W2(base, na):
        a = S(base); a.c16(0, 16320); a.b22(0x33, 1, 0, 'end'); a.c16(1, 8192); a.L('end'); return a.done()
    insert(c, p, W2); check(c)
    # L3: metadata of every HDR+ frame (v3 = Lljm) before the SpatialGainMap
    q = find(c, [0x0654, None, 0x206e, M('Lohv;', 'n', '(Lljm;)Lcom/google/googlex/gcam/SpatialGainMap;'), 0x0036])[0]
    if LOG: helper_call(c, q, 6, 8, 3)
    # Q2 (P181, removed: Llet.g is private to Llet -> IllegalAccessError); the quad step is in E now
    if False:
        q = find(c, [0x1612, 0x0816, 0x0000, 0x0a12, 0x0438])
        assert len(q) == 1, q
        q = q[0]; qi = {}
        fgL = F('Llet;->g:Lnns;')
        def Q2(base, na):
            a = S(base); a.L('t0')
            a.cs(6, KFLAG); a.inv(0x71, forname, [6]); a.mro(6); a.inv(0x6e, gdm, [6]); a.mro(6)
            a.c4(8, 0); a.raw(0x46 | 6 << 8, 6 | 8 << 8)
            a.raw(0x24 | 1 << 12, T('[Ljava/lang/Object;'), 4); a.mro(8)
            a.inv(0x6e, minv, [6, 4, 8]); a.mro(6)
            a.raw(0x20 | 8 << 8 | 6 << 12, T('Lnns;')); a.b21(0x38, 8, 't1')       # instance-of v8, v6, Lnns
            a.raw(0x1f | 6 << 8, T('Lnns;')); a.raw(0x1f | 4 << 8, T('Llet;'))
            a.raw(0x5b | 6 << 8 | 4 << 12, fgL)                                   # iput-object v6, v4, Llet.g
            a.L('t1'); a.L('h')
            w = a.done(); qi.update(t0=a.lab['t0'], t1=a.lab['t1'], h=a.lab['h']); return w
        insert(c, q, Q2); check(c)
        new = []
        for t in c.tries:
            st, cnt, h = t; e = st + cnt
            if st < qi['t1'] and e > qi['t0']:
                if st < qi['t0']: new.append([st, qi['t0'] - st, h])
                if e > qi['t1']: new.append([qi['t1'], e - qi['t1'], h])
            else: new.append(t)
        c.handlers.append([[], qi['h']]); new.append([qi['t0'], qi['t1'] - qi['t0'], len(c.handlers) - 1])
        c.tries = sorted(new, key=lambda t: t[0])
    fix_outs(c); out[m] = c.build()

    # ---- P290: GCam StaticMetadata (engine init dux.get, camera open ohv.q): every 8192 / 6144 becomes
    #      MenuValue('getWidth') != 0 ? 5792 / 4344 : 8192 / 6144  (RES button = 50 / 25 MP, camera restart) ----
    KRES = sid(d, 'getWidth'); MENU1 = M('LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    for cls_, nm_ in (('Ldux;', 'get'), ('Lohv;', 'q')):
        m = one(d, cls_, nm_); c = Code(raw, d.code[m]); n = 0
        while True:
            ks = [k for k in range(len(c.w) - 1) if (c.w[k] & 0xff) == 0x13 and c.w[k + 1] in (8192, 6144)]
            if not ks: break
            k = ks[0]; r = c.w[k] >> 8; big = c.w[k + 1]; small = 5792 if big == 8192 else 4344
            def B(base, na, r=r, big=big, small=small, k=k):
                a = S(base)
                a.cs(r, KRES); a.inv(0x71, MENU1, [r]); a.mr(r); a.b21(0x38, r, 'big')
                a.c16(r, small); a.go(na(k + 2))
                a.L('big'); a.raw(0x14 | r << 8, big & 0xffff, big >> 16); a.go(na(k + 2))   # const (31i): not re-found
                return a.done()
            insert(c, k, B)
            left = [j for j in range(len(c.w) - 1) if (c.w[j] & 0xff) == 0x13 and c.w[j + 1] == big and (c.w[j] >> 8) == r]
            assert left, 'original const not found'
            c.w[left[0] + 1] = big + 1                         # the original (now skipped) const: no longer matched
            n += 1
        check(c); fix_outs(c); print('P290 static size switch', cls_, nm_, n); out[m] = c.build()
    # ---- E: Llet.<init> -> binning helper ----
    m = one(d, 'Llet;', '<init>'); c = Code(raw, d.code[m])
    fa, fb_, fc, fg = (F('Llet;->a:I'), F('Llet;->b:I'), F('Llet;->c:I'), F('Llet;->g:Lnns;'))
    p = find(c, [0x2152, fa, 0x0013, 32, 0x0133])[0] + 6                     # after 'if-ne format, 32'
    assert c.w[p:p + 2] == [0x2152, fb_], c.w[p:p + 2]
    ret = len(c.w) - 1; assert c.w[ret] == 0x000e
    tNNS = T('Lnns;'); tOA = T('[Ljava/lang/Object;')
    info = {}
    def E(base, na):
        a = S(base)
        a.raw(0x52 | 1 << 8 | 2 << 12, fb_)                                  # iget v1, v2, b
        if QUAD:                                                             # 8192 wide + 'quadTo' -> quad helper too
            a.c16(0, 16320); a.b22(0x32, 1, 0, 'go')
            a.c16(0, 8192); a.b22(0x33, 1, 0, na(p))
            a.inv(0x71, props, []); a.mro(0); a.cs(1, KQUAD); a.inv(0x72, get, [0, 1]); a.mro(0)
            a.b21(0x38, 0, na(p))
            a.L('go')
        else:
            a.c16(0, 16320); a.b22(0x33, 1, 0, na(p))                         # not 16320 -> original code
        a.L('t0')
        a.cs(0, KFLAG); a.inv(0x71, forname, [0]); a.mro(0)
        a.inv(0x6e, gdm, [0]); a.mro(0)
        a.c4(1, 0); a.raw(0x46, 0x0100)                                      # aget-object v0, v0, v1
        a.raw(0x24 | 1 << 12, tOA, 3)                                        # filled-new-array {v3}, Object[]
        a.mro(1); a.c4(3, 0)
        a.inv(0x6e, minv, [0, 3, 1]); a.mro(0)
        a.L('t1')
        a.b21(0x38, 0, na(ret))
        a.raw(0x1f, tNNS)                                                    # check-cast v0, Lnns
        a.raw(0x5b | 0 << 8 | 2 << 12, fg)                                   # iput-object v0, v2, g
        if QUAD: a.raw(0x5b | 0 << 8 | 2 << 12, F('Llet;->d:Ljava/lang/Object;'))   # d = g: marks our planes (lock object)
        # P290: frame size from props 'getWidth' (Integer w << 16 | h, set by TemporalBinning.a), else 8192 x 6144
        a.inv(0x71, props, []); a.mro(0); a.cs(1, KDIM); a.inv(0x72, get, [0, 1]); a.mro(0); a.b21(0x38, 0, 'dd')
        a.raw(0x1f, T('Ljava/lang/Integer;')); a.inv(0x6e, M('Ljava/lang/Integer;', 'intValue', '()I'), [0]); a.raw(0x0a | 0 << 8)
        a.raw(0xe1 | 1 << 8, 0 | 16 << 8); a.raw(0x59 | 1 << 8 | 2 << 12, fb_)              # width = v >> 16
        a.raw(0xe0 | 0 << 8, 0 | 16 << 8); a.raw(0xe2 | 0 << 8, 0 | 16 << 8); a.raw(0x59 | 0 << 8 | 2 << 12, fc)   # height
        a.go(na(ret))
        a.L('dd')
        a.c16(0, 8192); a.raw(0x59 | 0 << 8 | 2 << 12, fb_)
        a.c16(0, 6144); a.raw(0x59 | 0 << 8 | 2 << 12, fc)
        a.go(na(ret))
        w = a.done(); info['t0'] = a.lab['t0']; info['t1'] = a.lab['t1']; return w
    L = insert(c, p, E); check(c)
    # catch-all for the reflective call -> return-void
    newret = len(c.w) - 1; assert c.w[newret] == 0x000e
    for s_, n_, h_ in c.tries: assert s_ + n_ <= info['t0'] or s_ >= info['t1'], 'try overlap'
    c.handlers.append([[], newret]); c.tries.append([info['t0'], info['t1'] - info['t0'], len(c.handlers) - 1])
    c.tries.sort(key=lambda t: t[0])
    fix_outs(c); out[m] = c.build()

    # ---- F: Llet.f() -> no HardwareBuffer for a binned frame ----
    m = one(d, 'Llet;', 'f'); c = Code(raw, d.code[m])
    fe = F('Llet;->e:Landroid/media/Image;'); fd_ = F('Llet;->d:Ljava/lang/Object;')
    def Fb(base, na):
        a = S(base)
        if QUAD:
            a.raw(0x54 | 0 << 8 | 2 << 12, fg); a.b21(0x38, 0, 'w')             # Llet.g null -> width test
            a.raw(0x54 | 1 << 8 | 2 << 12, fd_); a.b22(0x33, 0, 1, 'w')         # d != g: GCam's own plane list
            a.c4(0, 0); a.raw(0x0011)                                         # our planes (E set d = g): no HardwareBuffer
            a.L('w')
        a.raw(0x52 | 0 << 8 | 2 << 12, fb_)                                  # iget v0, v2, b
        a.raw(0x54 | 1 << 8 | 2 << 12, fe); a.inv(0x6e, imgw, [1]); a.mr(1)
        a.b22(0x32, 0, 1, na(0))                                             # same width -> original
        a.c4(0, 0); a.raw(0x0011)                                            # return-object null
        return a.done()
    Lf = insert(c, 0, Fb); check(c)
    # getWidth on a closed Image throws: catch-all -> original code (block start + Lf)
    off = 10 if QUAD else 0                                                   # the quad prefix (10 units) comes first
    for s_, n_, h_ in c.tries: assert s_ >= 7 + off, 'try overlap F'
    c.handlers.append([[], Lf]); c.tries.append([4 + off, 3, len(c.handlers) - 1]); c.tries.sort(key=lambda t: t[0])
    fix_outs(c); out[m] = c.build()

    # ---- QC: Llet.close() -> release a remosaic pool buffer (Llet.g) first ----
    if QUAD:
        m = one(d, 'Llet;', 'close'); c = Code(raw, d.code[m])
        fd = F('Llet;->d:Ljava/lang/Object;')
        assert c.regs == 3 and c.ins == 1 and c.w[:3] == [0x0054 | 2 << 12, fd, 0x011d - 0x0100 + 0x0000] or True
        a = S(0)
        a.raw(0x54 | 0 << 8 | 4 << 12, fg); a.b21(0x38, 0, 'orig')               # v4 = this
        a.raw(0x54 | 1 << 8 | 4 << 12, fd); a.b22(0x33, 0, 1, 'orig')            # d != g: not our planes
        a.L('t0')
        a.cs(1, KFLAG); a.inv(0x71, forname, [1]); a.mro(1); a.inv(0x6e, gdm, [1]); a.mro(1)
        a.c4(2, 0); a.raw(0x46 | 1 << 8, 1 | 2 << 8)
        a.raw(0x24 | 1 << 12, T('[Ljava/lang/Object;'), 0); a.mro(2)
        a.inv(0x6e, minv, [1, 0, 2])
        a.L('t1')
        a.L('orig')
        a.raw(0x54 | 0 << 8 | 4 << 12, fd); a.raw(0x1d | 0 << 8)                # monitor-enter v0
        a.L('m0')
        a.raw(0x54 | 1 << 8 | 4 << 12, fe); a.inv(0x6e, M('Landroid/media/Image;', 'close', '()V'), [1])
        a.raw(0x1e | 0 << 8)                                                      # monitor-exit v0
        a.L('m1')
        a.raw(0x000e)
        a.L('mh')
        a.raw(0x0d | 1 << 8); a.raw(0x1e | 0 << 8); a.raw(0x27 | 1 << 8)         # move-exception, monitor-exit, throw
        w = a.done()
        c.regs, c.ins, c.w, c.debug = 5, 1, w, 0
        c.handlers = [[[], a.lab['orig']], [[], a.lab['mh']]]
        c.tries = [[a.lab['t0'], a.lab['t1'] - a.lab['t0'], 0], [a.lab['m0'], a.lab['m1'] - a.lab['m0'], 1]]
        fix_outs(c); out[m] = c.build()

    # ---- P290: double-tap config dialog: neutral 'Delete' -> 'Settings' (opens LMC settings); Quit / Import unchanged ----
    BB = 'Lcom/google/android/apps/camera/bottombar/'
    G2 = BB + 'DLock$GestureListener$2;'
    fld = lambda c, t, n: [i for i, f in enumerate(d.fields) if f == (c, t, n)][0]
    m = one(d, G2, 'onClick'); c = Code(raw, d.code[m])
    a = S(0)
    a.raw(0x54 | 0 << 8 | 6 << 12, fld(G2, BB + 'DLock$GestureListener;', 'f$0'))
    a.raw(0x54 | 0 << 8 | 0 << 12, fld(BB + 'DLock$GestureListener;', BB + 'BottomBar;', 'this$0'))
    a.raw(0x54 | 0 << 8 | 0 << 12, fld(BB + 'BottomBar;', 'Landroid/content/Context;', 'appContext'))
    a.raw(0x22 | 1 << 8, T('Landroid/content/Intent;'))
    a.raw(0x1c | 2 << 8, T('Lcom/google/android/apps/camera/legacy/app/settings/CameraSettingsActivity;'))
    a.inv(0x70, M('Landroid/content/Intent;', '<init>', '(Landroid/content/Context;Ljava/lang/Class;)V'), [1, 0, 2])
    a.raw(0x15 | 2 << 8, 0x1000)                                                 # const/high16 v2, FLAG_ACTIVITY_NEW_TASK
    a.inv(0x6e, M('Landroid/content/Intent;', 'addFlags', '(I)Landroid/content/Intent;'), [1, 2])
    a.inv(0x6e, M('Landroid/content/Context;', 'startActivity', '(Landroid/content/Intent;)V'), [0, 1])
    a.raw(0x000e)
    c.w = a.done(); c.tries = []; c.handlers = []; c.debug = 0
    assert c.regs == 9 and c.ins == 3
    fix_outs(c); out[m] = c.build()
    # P290: shutter tap timing (log): ShutterButton.performClick start -> code 97, blocked click -> code 96
    m = one(d, 'Lcom/google/android/apps/camera/ui/shutterbutton/ShutterButton;', 'performClick'); c = Code(raw, d.code[m])
    assert c.regs == 4 and c.w[6] & 0xff == 0x6e and c.w[9] == 0x0012, [hex(x) for x in c.w[:12]]
    def TAP(code):
        def f(base, na):
            a = S(base)
            a.c16(1, code); a.inv(0x71, M('Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;'), [1]); a.mro(1)
            a.cs(0, sid(d, 'getWidth')); a.inv(0x71, forname, [0]); a.mro(0)
            a.inv(0x6e, M('Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;'), [0]); a.mro(0)
            a.raw(0x1f | 0 << 8, T('Ljava/util/Comparator;')); a.c4(2, 0)
            a.inv(0x72, M('Ljava/util/Comparator;', 'compare', '(Ljava/lang/Object;Ljava/lang/Object;)I'), [0, 1, 2])
            return a.done()
        return f
    if LOG:
        insert(c, 6, TAP(96)); insert(c, 0, TAP(97)); check(c); fix_outs(c); out[m] = c.build()
    # P290: GCam's shutter progress ring (ShutterButtonProgressOverlay.<init>, before return): hand it to the helper
    m = one(d, 'Lcom/google/android/apps/camera/ui/shutterbutton/ShutterButtonProgressOverlay;', '<init>'); c = Code(raw, d.code[m])
    assert c.regs == 5 and c.w[130] == 0x000e, [hex(x) for x in c.w[126:131]]
    def SP(base, na):
        a = S(base)
        a.cs(0, sid(d, 'getWidth')); a.inv(0x71, forname, [0]); a.mro(0)
        a.inv(0x6e, M('Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;'), [0]); a.mro(0)
        a.raw(0x1f | 0 << 8, T('Ljava/util/Comparator;')); a.c4(3, 0)
        a.inv(0x72, M('Ljava/util/Comparator;', 'compare', '(Ljava/lang/Object;Ljava/lang/Object;)I'), [0, 2, 3])
        return a.done()
    insert(c, 130, SP); check(c); fix_outs(c); out[m] = c.build()
    # P290: file-name date format (Lhxm.a, right after new SimpleDateFormat(pattern + suffix)): helper wraps it in LTBDF,
    #       which adds _XR / _ER / _SR to 50 / 25 MP shots; helper result comes back as props.remove(sdf)
    m = one(d, 'Lhxm;', 'a'); c = Code(raw, d.code[m])
    assert c.w[55] & 0xff == 0x70 and c.w[58] == 0x0322, [hex(x) for x in c.w[55:60]]
    def DF(base, na):
        a = S(base)
        a.cs(3, sid(d, 'getWidth')); a.inv(0x71, forname, [3]); a.mro(3)
        a.inv(0x6e, M('Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;'), [3]); a.mro(3)
        a.raw(0x1f | 3 << 8, T('Ljava/util/Comparator;')); a.c4(4, 0)
        a.inv(0x72, M('Ljava/util/Comparator;', 'compare', '(Ljava/lang/Object;Ljava/lang/Object;)I'), [3, 2, 4])
        a.inv(0x71, props, []); a.mro(3); a.inv(0x72, rem, [3, 2]); a.mro(4); a.b21(0x38, 4, 'k')
        a.raw(0x1f | 4 << 8, T('Ljava/text/DateFormat;')); a.raw(0x07 | 2 << 8 | 4 << 12)
        a.L('k'); return a.done()
    insert(c, 58, DF); check(c); fix_outs(c); out[m] = c.build()
    # P290: Import restart (GestureListener.onRestart, before System.exit at 37): profile helper code 98 = unpack the
    #       imported file's 3-mode bundle into /LMC8.3/XML/auto/ and re-embed it
    m = one(d, BB + 'DLock$GestureListener;', 'onRestart'); c = Code(raw, d.code[m])
    assert c.regs == 4 and c.w[37] == 0x0212 and c.w[38] & 0xff == 0x71, c.w[34:40]
    def IR(base, na):
        a = S(base)
        a.c16(1, 98); a.inv(0x71, M('Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;'), [1]); a.mro(1)
        a.cs(0, sid(d, 'getWidth')); a.inv(0x71, forname, [0]); a.mro(0)
        a.inv(0x6e, M('Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;'), [0]); a.mro(0)
        a.raw(0x1f | 0 << 8, T('Ljava/util/Comparator;')); a.c4(2, 0)
        a.inv(0x72, M('Ljava/util/Comparator;', 'compare', '(Ljava/lang/Object;Ljava/lang/Object;)I'), [0, 1, 2])
        return a.done()
    insert(c, 37, IR); check(c); fix_outs(c); out[m] = c.build()
    # the builder method: const-string 'Delete' -> 'Settings'
    sdel, sset = sid(d, 'Delete'), sid(d, 'Settings'); nd = 0
    for mm in [i for i in range(len(d.methods)) if d.methods[i][0] == BB + 'DLock$GestureListener;']:
        if mm not in d.code or not d.code[mm] or mm in out: continue
        cc = Code(raw, d.code[mm]); hit = False
        for k, _, pl in walk(cc.w):
            if not pl and cc.w[k] & 0xff == 0x1a and cc.w[k + 1] == sdel:
                assert sset < 0x10000; cc.w[k + 1] = sset; hit = True; nd += 1
        if hit: out[mm] = cc.build()
    assert nd == 1, nd
    o = bytearray(relocate(raw, out)); fix_hdr(o)
    if os.environ.get('EVRIGHT', '1') == '1':
        # exposure sliders (+ lock): gravity END|CENTER_VERTICAL (8388629; END = left in this RTL view) -> RIGHT|CENTER_VERTICAL
        open('/tmp/_p175e.dex', 'wb').write(bytes(o)); de = Dex('/tmp/_p175e.dex'); n = 0
        for nm in ('h', 'i'):
            m = one(de, 'Lcom/google/android/apps/camera/evcomp/EvCompView;', nm); co = de.code[m]
            nw = struct.unpack_from('<I', o, co + 12)[0]; w = struct.unpack_from('<%dH' % nw, o, co + 16)
            for k in range(nw - 2):
                if w[k] & 0xff == 0x14 and w[k + 1] == 8388629 & 0xffff and w[k + 2] == 8388629 >> 16:
                    struct.pack_into('<HH', o, co + 16 + 2 * (k + 1), 21, 0); n += 1
        assert n == 3, n
        fix_hdr(o)
    return bytes(o)


def patch_classes2(raw):
    d = Dex.__new__(Dex)
    open('/tmp/_p175_2.dex', 'wb').write(raw); d = Dex('/tmp/_p175_2.dex')
    o = bytearray(raw)
    old, new = d.strings.index('pref_shading_mode_key'), d.strings.index('setTemporalBinning')
    n = 0
    for cls, name in (('LMC/UI/Button/Leica$1;', 'onCheckedChanged'), ('LMC/UI/Button/Leica;', 'init')):
        m = one(d, cls, name); off = d.code[m]
        nw = struct.unpack_from('<I', raw, off + 12)[0]
        for i in range(nw - 1):
            w0, w1 = struct.unpack_from('<HH', raw, off + 16 + 2 * i)
            if (w0 & 0xff) == 0x1a and w1 == old:
                struct.pack_into('<H', o, off + 16 + 2 * i + 2, new); n += 1
    assert n == 2, n
    # P: per-mode ZSL frame count. LMC/lensvalue.SetLensValue('pref_zsl_frames_key') gets a mode suffix:
    #    RES OFF -> none (12 MP, unchanged), RES ON -> 'FULL' (50 MP), RES ON + Leica ON -> 'leica' (200 MP)
    raw2 = bytes(o)
    open('/tmp/_p175_2b.dex', 'wb').write(raw2); d = Dex('/tmp/_p175_2b.dex')
    sb_tos = mid(d, 'Ljava/lang/StringBuilder;', 'toString', '()Ljava/lang/String;')
    seq = mid(d, 'Ljava/lang/String;', 'equals', '(Ljava/lang/Object;)Z')
    menu = mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    app = mid(d, 'Ljava/lang/StringBuilder;', 'append', '(Ljava/lang/String;)Ljava/lang/StringBuilder;')
    s2 = lambda x: d.strings.index(x)
    def P(base, na):
        a = S(base)
        a.cs(2, s2('pref_zsl_frames_key')); a.inv(0x6e, seq, [5, 2]); a.mr(2); a.b21(0x38, 2, 'end')
        a.cs(2, s2('pref_upscale_key')); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'end')
        a.cs(1, s2('FULL'))
        if not NO200:
            a.cs(2, s2('setTemporalBinning')); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'mot')
            a.cs(1, s2('leica')); a.go('app')
        a.L('mot')                                       # Motion (LDR button) -> its own frame count, suffix 'action'
        a.cs(2, s2('pref_enable_ldr_key')); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'app')
        a.cs(1, s2('action'))
        a.L('app'); a.inv(0x6e, app, [0, 1])
        a.L('end'); return a.done()
    outs2 = {}
    for name in ('SetLensValue', 'SetLensValueBack'):     # readers / the long-press ZSL selector (read + write)
        m = one(d, 'LMC/lensvalue;', name); c = Code(raw2, d.code[m])
        p = [q for q in range(len(c.w) - 1) if c.w[q] == 0x106e and c.w[q + 1] == sb_tos]; assert len(p) == 1, p
        assert c.regs == 6 and c.ins == 1
        insert(c, p[0], P); check(c); fix_outs(c); outs2[m] = c.build()
    o = bytearray(relocate(raw2, outs2))
    fix_hdr(o)
    # MO: LDR button = Motion. LibPatcher.copyLib ignores 'pref_enable_ldr_key' (no LDR libs), LDR$2.onClick no restart
    raw3 = bytes(o); open('/tmp/_p175_2c.dex', 'wb').write(raw3); d = Dex('/tmp/_p175_2c.dex'); o = bytearray(raw3)
    LK = d.strings.index('pref_enable_ldr_key')
    m = one(d, 'LMC/LibPatcher;', 'copyLib'); off = d.code[m] + 16
    nw = struct.unpack_from('<I', raw3, d.code[m] + 12)[0]
    w = list(struct.unpack_from('<%dH' % nw, raw3, off))
    hit = [i for i in range(nw - 6) if w[i] == 0x001a and w[i + 1] == LK and w[i + 2] == 0x1071 and w[i + 5] == 0x000a
           and w[i + 6] == 0x0038]
    assert len(hit) == 1, hit
    j = hit[0] + 6; struct.pack_into('<HH', o, off + 2 * j, 0x0029, w[j + 1])      # if-eqz v0, +X -> goto/16 +X
    # PR: the PRO patcher profile follows RES: copyLib applies the PRO values when 'pref_upscale_key' (50 MP) is on,
    #     not when 'pref_enable_pro_key' is (RES toggling already restarts and re-patches)
    if os.environ.get('PRO50', '0') == '1':
        PK, UK = d.strings.index('pref_enable_pro_key'), d.strings.index('pref_upscale_key')
        hp = [i for i in range(nw - 2) if w[i] & 0xff == 0x1a and w[i + 1] == PK and w[i + 2] == 0x1071]
        assert len(hp) == 1, hp
        struct.pack_into('<H', o, off + 2 * hp[0] + 2, UK)
    # ML: Motion manual panel. LDR.UpdateUi (init + every toggle) -> Class.forName("action").newInstance().equals(this):
    #     Laction.equals(View) posts the panel sync (shown while 'pref_enable_ldr_key' is on, hidden when off)
    if os.environ.get('NOMANUAL') != '1':
        lm = one(d, 'LMC/UI/Button/LDR;', 'UpdateUi'); lc = Code(raw3, d.code[lm])
        assert lc.regs == 9 and lc.ins == 2 and lc.w[8] == 0x000e and lc.w[5] & 0xff == 0x6e
        fnm = mid(d, 'Ljava/lang/Class;', 'forName', '(Ljava/lang/String;)Ljava/lang/Class;')
        nim = mid(d, 'Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;')
        eqm = mid(d, 'Ljava/lang/Object;', 'equals', '(Ljava/lang/Object;)Z'); sac = d.strings.index('action')
        def ML(base, na):
            a = S(base)
            a.cs(0, sac); a.inv(0x71, fnm, [0]); a.mro(0); a.inv(0x6e, nim, [0]); a.mro(0)
            a.inv(0x6e, eqm, [0, 7]); return a.done()
        insert(lc, 8, ML); check(lc); fix_outs(lc)
        o = bytearray(relocate(raw3, {lm: lc.build()})); fix_hdr(o)
        raw3 = bytes(o); open('/tmp/_p175_2c.dex', 'wb').write(raw3); d = Dex('/tmp/_p175_2c.dex')
    m = one(d, 'LMC/UI/Button/LDR$2;', 'onClick'); off = d.code[m] + 16
    assert struct.unpack_from('<H', raw3, off)[0] == 0x0071
    struct.pack_into('<HHH', o, off, 0x000e, 0, 0)                                  # return-void
    if NO200:
        m = one(d, 'LMC/UI/Button/Leica$1;', 'onCheckedChanged'); off = d.code[m] + 16
        nw = struct.unpack_from('<I', raw3, d.code[m] + 12)[0]
        w = list(struct.unpack_from('<%dH' % nw, raw3, off))
        ri = [i for i in range(nw - 3) if w[i] == 0x0071 and w[i + 3] == 0x000e]
        assert len(ri) == 1, ri
        struct.pack_into('<HHH', o, off + 2 * ri[0], 0, 0, 0)                        # ReInit() -> nop
    if REM3:
        # Leica$1: SelState = (SelState + 1) % 3 ('setTemporalBinning' 0 XR, 1 ER, 2 SR)
        rr = [i for i in range(nw - 1) if (w[i] & 0xff) == 0xdc and (w[i + 1] >> 8) == 2]
        assert len(rr) == 1, rr
        struct.pack_into('<H', o, off + 2 * rr[0] + 2, (w[rr[0] + 1] & 0xff) | 3 << 8)
        fix_hdr(o)
        # Leica.UpdateUi: state 2 -> drawable 'aperture_on' (SR icon)
        raw4 = bytes(o); open('/tmp/_p175_2d.dex', 'wb').write(raw4); d = Dex('/tmp/_p175_2d.dex')
        LC = 'LMC/UI/Button/Leica;'
        fsel = [i for i, f in enumerate(d.fields) if f == (LC, 'I', 'SelState')]; assert len(fsel) == 1, fsel
        gres = mid(d, LC, 'getResources', '()Landroid/content/res/Resources;')
        gpk = mid(d, 'Landroid/content/Context;', 'getPackageName', '()Ljava/lang/String;')
        gid = mid(d, 'Landroid/content/res/Resources;', 'getIdentifier', '(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)I')
        sbr = mid(d, LC, 'setBackgroundResource', '(I)V'); inv = mid(d, LC, 'invalidate', '()V')
        def U(base, na):
            a = S(base)
            a.raw(0x60 | 3 << 8, fsel[0]); a.c4(4, 2); a.b22(0x33, 3, 4, 'end')
            a.c32(0, 0x7f08043e)                                          # R.drawable.aperture_on (P174B resources)
            a.inv(0x6e, sbr, [7, 0]); a.inv(0x6e, inv, [7]); a.raw(0x000e)
            if len(a.w) % 2: a.raw(0)
            a.L('end'); return a.done()
        m = one(d, LC, 'UpdateUi'); c = Code(raw4, d.code[m])
        assert c.regs == 9 and c.ins == 2
        insert(c, 0, U); check(c); fix_outs(c)
        o = bytearray(relocate(raw4, {m: c.build()}))
    fix_hdr(o)
    # ---- P290: RES button = 12 / 50 / 25 MP (SelState 0 / 1 / 2): pref_upscale_key = state != 0 (RES as before),
    #      'getWidth' = state == 2 (25 MP: GCam StaticMetadata 5792 x 4344 + our resample); camera restart as before.
    #      Icon: 0 upscale_off, 1 upscale_on, 2 upscale_on dimmed (alpha 0.45). ----
    raw5 = bytes(o); open('/tmp/_p290_2.dex', 'wb').write(raw5); d = Dex('/tmp/_p290_2.dex')
    UC = 'LMC/UI/Button/Upscale;'
    fst = [i for i, f in enumerate(d.fields) if f == (UC, 'I', 'SelState')]; assert len(fst) == 1, fst
    s2 = lambda x: d.strings.index(x)
    menu = mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I'); setv = mid(d, 'LMC/pref;', 'setValue', '(Ljava/lang/String;I)V')
    gres = mid(d, UC, 'getResources', '()Landroid/content/res/Resources;')
    gpk = mid(d, 'Landroid/content/Context;', 'getPackageName', '()Ljava/lang/String;')
    gid = mid(d, 'Landroid/content/res/Resources;', 'getIdentifier', '(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)I')
    sbr = mid(d, UC, 'setBackgroundResource', '(I)V'); inv = mid(d, UC, 'invalidate', '()V')
    salpha = mid(d, 'Landroid/view/View;', 'setAlpha', '(F)V')
    repl = {}
    # onCheckedChanged(v6 this$1, v7 button, v8 checked): state cycle + both prefs, then the original tail at 13
    m = one(d, 'LMC/UI/Button/Upscale$1;', 'onCheckedChanged'); c = Code(raw5, d.code[m])
    assert c.regs == 9 and c.w[13] & 0xff == 0x6e, c.w[:16]
    # P290 settings profiles: Class.forName('getWidth') (our classes3 Comparator) .compare(Integer code, null)
    fnm = mid(d, 'Ljava/lang/Class;', 'forName', '(Ljava/lang/String;)Ljava/lang/Class;')
    nin = mid(d, 'Ljava/lang/Class;', 'newInstance', '()Ljava/lang/Object;')
    cmpm = mid(d, 'Ljava/util/Comparator;', 'compare', '(Ljava/lang/Object;Ljava/lang/Object;)I')
    ivo = mid(d, 'Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    tcmp = d.types.index('Ljava/util/Comparator;')
    def prof(a, rc, r0, r1):                    # code in int register rc (clobbered), r0 / r1 scratch
        a.inv(0x71, ivo, [rc]); a.mro(rc)
        a.cs(r0, s2('getWidth')); a.inv(0x71, fnm, [r0]); a.mro(r0); a.inv(0x6e, nin, [r0]); a.mro(r0)
        a.raw(0x1f | r0 << 8, tcmp); a.c4(r1, 0); a.inv(0x72, cmpm, [r0, rc, r1])
    def OC(base, na):
        a = S(base)
        a.raw(0x60 | 5 << 8, fst[0]); prof(a, 5, 0, 4)                                                    # save mode left
        a.raw(0x60 | 2 << 8, fst[0]); a.raw(0xd8 | 2 << 8, 2 | 1 << 8); a.raw(0xdc | 2 << 8, 2 | 3 << 8)   # (s + 1) % 3
        a.raw(0x67 | 2 << 8, fst[0])
        a.c4(3, 0); a.b21(0x38, 2, 'r0'); a.c4(3, 1)
        a.L('r0'); a.cs(1, s2('pref_upscale_key')); a.inv(0x71, setv, [1, 3])
        a.c4(3, 0); a.c4(4, 2); a.b22(0x33, 2, 4, 'w0'); a.c4(3, 1)
        a.L('w0'); a.cs(1, s2('getWidth')); a.inv(0x71, setv, [1, 3])
        a.raw(0xd8 | 5 << 8, 2 | 10 << 8); prof(a, 5, 0, 4)                                               # plan mode entered
        a.go(na(13))
        return a.done()
    insert(c, 0, OC); check(c); fix_outs(c); repl[m] = c.build()
    # init(v4 this, v5 ctx): SelState = RES ? (getWidth ? 2 : 1) : 0  (before 'sput SelState' at 28)
    m2 = one(d, UC, 'init'); c2 = Code(raw5, d.code[m2])
    assert c2.regs == 6 and c2.w[28] & 0xff == 0x67, c2.w[24:32]
    def IN(base, na):
        a = S(base)
        a.b21(0x38, 0, 'i0'); a.cs(1, s2('getWidth')); a.inv(0x71, menu, [1]); a.mr(1); a.b21(0x38, 1, 'i0'); a.c4(0, 2)
        a.L('i0'); return a.done()
    insert(c2, 28, IN); check(c2); fix_outs(c2); repl[m2] = c2.build()
    # UpdateUi(v7 this, v8 ctx): icon + alpha for the 3 states, return
    m3 = one(d, UC, 'UpdateUi'); c3 = Code(raw5, d.code[m3])
    assert c3.regs == 9 and c3.ins == 2
    import struct as _st
    def UU(base, na):
        a = S(base)
        a.raw(0x60 | 3 << 8, fst[0])
        a.c4(5, 2); a.b22(0x33, 3, 5, 'u0')
        a.c32(1, 0x7f08043d); a.go('u2s')                              # P290: 25 MP -> R.drawable.aperture_off ('25')
        a.L('u0'); a.cs(4, s2('upscale_off')); a.b21(0x38, 3, 'u1'); a.cs(4, s2('upscale_on'))
        a.L('u1'); a.inv(0x6e, gres, [7]); a.mro(0); a.cs(5, s2('drawable')); a.inv(0x6e, gpk, [8]); a.mro(6)
        a.inv(0x6e, gid, [0, 4, 5, 6]); a.mr(1)
        a.L('u2s'); a.inv(0x6e, sbr, [7, 1])
        one_ = _st.unpack('<I', _st.pack('<f', 1.0))[0]; dim = _st.unpack('<I', _st.pack('<f', 1.0))[0]
        a.raw(0x14 | 2 << 8, one_ & 0xffff, one_ >> 16); a.c4(4, 2); a.b22(0x33, 3, 4, 'u2')
        a.raw(0x14 | 2 << 8, dim & 0xffff, dim >> 16)
        a.L('u2'); a.inv(0x6e, salpha, [7, 2]); a.inv(0x6e, inv, [7]); a.raw(0x000e)
        if len(a.w) % 2: a.raw(0)
        return a.done()
    insert(c3, 0, UU); check(c3); fix_outs(c3); repl[m3] = c3.build()
    # LMC main.onRestart: put the planned profile in place just before System.exit (index 50)
    m4 = one(d, 'LMC/main;', 'onRestart'); c4 = Code(raw5, d.code[m4])
    assert c4.regs == 5 and c4.w[50] == 0x0212 and c4.w[51] & 0xff == 0x71, c4.w[48:54]
    def RS(base, na):
        a = S(base); a.c16(3, 99); prof(a, 3, 0, 1); return a.done()
    insert(c4, 50, RS); check(c4); fix_outs(c4); repl[m4] = c4.build()
    o = bytearray(relocate(raw5, repl))
    fix_hdr(o); return bytes(o)


def rebuild_apk(src, dst, repl, add):
    zi = zipfile.ZipFile(src)
    with open(src, 'rb') as f: blob = f.read()
    out = bytearray(); central = bytearray(); n = 0
    def emit(name, ver, flag, meth, mt, md, crc, csz, usz, payload, cver, eattr):
        nonlocal out, central, n
        fname = name.encode(); off = len(out); extra = b''
        if meth == 0:
            align = 16384 if name.endswith('.so') else 4
            need = (-(off + 30 + len(fname))) % align
            if need and need < 4: need += align
            if need: extra = struct.pack('<HH', 0xd935, need - 4) + b'\0' * (need - 4)
        out += struct.pack('<IHHHHHIIIHH', 0x04034b50, ver, flag, meth, mt, md, crc, csz, usz, len(fname), len(extra)) + fname + extra + payload
        central += struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, cver, ver, flag, meth, mt, md, crc, csz, usz, len(fname),
                               0, 0, 0, 0, eattr, off) + fname
        n += 1
    def deflate(data):
        co = zlib.compressobj(9, zlib.DEFLATED, -15); return co.compress(data) + co.flush()
    for info in zi.infolist():
        name = info.filename
        if name.startswith('META-INF/') and name.rsplit('.', 1)[-1] in ('SF', 'RSA', 'DSA', 'EC', 'MF'): continue
        lh = info.header_offset
        sig, ver, flag, meth, mt, md, crc, csz, usz, nl, el = struct.unpack_from('<IHHHHHIIIHH', blob, lh)
        assert meth == 8 or not name.endswith('.so') or True
        dstart = lh + 30 + nl + el
        if name in repl:
            data = repl[name]; comp = deflate(data)
            emit(name, ver, flag & ~8, 8, mt, md, zlib.crc32(data) & 0xffffffff, len(comp), len(data), comp,
                 info.create_version | (info.create_system << 8), info.external_attr)
        else:
            assert meth == 8 or meth == 0
            emit(name, ver, flag & ~8, meth, mt, md, info.CRC, info.compress_size, info.file_size,
                 blob[dstart:dstart + info.compress_size], info.create_version | (info.create_system << 8), info.external_attr)
    for name, data in add.items():
        comp = deflate(data)
        emit(name, 20, 0, 8, 0, 0x5b74, zlib.crc32(data) & 0xffffffff, len(comp), len(data), comp, 20, 0)
    cd = len(out); out += central
    out += struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, n, n, len(central), cd, 0)
    open(dst, 'wb').write(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src)
    c1 = patch_classes(z.read('classes.dex')); c2 = patch_classes2(z.read('classes2.dex'))
    c3 = dexgen.build_classes3()
    so = open(os.path.join(HERE, 'libtbin_dump.so' if os.environ.get('TBDUMP') == '1' else 'libtbin.so'), 'rb').read()
    import icons
    res = icons.resources(z, NO200, REM3) if os.environ.get('NOICONS') != '1' else {}
    rebuild_apk(src, dst, dict({'classes.dex': c1, 'classes2.dex': c2}, **res), {'classes3.dex': c3, 'lib/arm64-v8a/libtbin.so': so})
    for nm, b in (('classes.dex', c1), ('classes2.dex', c2), ('classes3.dex', c3), ('libtbin.so', so)):
        print(nm, hashlib.sha256(b).hexdigest())
    print('wrote', dst)
