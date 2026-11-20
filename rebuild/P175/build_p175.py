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
    out = {}

    def flag_block(a, rp, rk, lbl_end):
        """rk = props.get(FLAG) ; if-eqz rk -> lbl_end   (rp, rk temps)"""
        a.inv(0x71, props, []); a.mro(rp); a.cs(rk, KFLAG); a.inv(0x72, get, [rp, rk]); a.mro(rk)
        a.b21(0x38, rk, lbl_end)

    def reader_block(a, rp, rt, ru, dev_from, wreg, hreg, nreg):
        """size selection; rp/rt/ru temps; dev_from(a, reg) loads the CameraDevice (or leaves null -> end)."""
        a.inv(0x71, props, []); a.mro(rp)
        a.cs(rt, KFLAG); a.inv(0x72, rem, [rp, rt])
        a.cs(rt, KPREF); a.inv(0x71, menu, [rt]); a.mr(rt); a.b21(0x38, rt, 'end')
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
        a.cs(5, KPREF); a.inv(0x71, menu, [5]); a.mr(5); a.b21(0x38, 5, 'end')
        dev_llel(a, 5); a.b21(0x38, 5, 'end')
        a.inv(0x6e, getid, [5]); a.mro(5)
        a.cs(15, S3); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x39, 15, 'main')
        a.cs(15, S5); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x39, 15, 'tele')
        a.cs(15, sid(d, '9')); a.inv(0x6e, seq, [15, 5]); a.mr(15); a.b21(0x38, 15, 'end')
        a.L('tele')
        a.c16(10, 12288); a.go('set')
        a.L('main'); a.c16(10, 12256)
        a.L('set'); a.c16(9, 16320); a.c4(12, 6)
        a.cs(5, KFLAG); a.inv(0x72, put, [4, 5, 5])
        a.L('end')
        return a.done()
    insert(c, p, R1); check(c)
    # flag removal on every session build (RES OFF path too): before 'pref_upscale_key' MenuValue
    q = find(c, [0x0d1a, sid(d, 'pref_upscale_key')])[0]
    def R1b(base, na):
        a = S(base); a.inv(0x71, props, []); a.mro(12); a.cs(13, KFLAG); a.inv(0x72, rem, [12, 13]); return a.done()
    insert(c, q, R1b); check(c); fix_outs(c); out[m] = c.build()

    # ---- R2: Llfe.e ----
    m = one(d, 'Llfe;', 'e'); c = Code(raw, d.code[m])
    p = find(c, [0x0513, 8192, 0x0613, 6144, 0x0713, 32, 0x0813, 25])[0] + 8 + 3
    assert (c.w[p] & 0xff) == 0x77, hex(c.w[p])
    def R2(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(1)
        a.cs(2, KFLAG); a.inv(0x72, rem, [1, 2])
        a.cs(2, KPREF); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'end')
        a.cs(2, KCAM); a.inv(0x72, get, [1, 2]); a.mro(2); a.b21(0x38, 2, 'end')
        a.raw(0x1f | 2 << 8, T('Landroid/hardware/camera2/CameraDevice;'))
        a.inv(0x6e, getid, [2]); a.mro(2)
        a.cs(3, S3); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x39, 3, 'main')
        a.cs(3, S5); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x39, 3, 'tele')
        a.cs(3, sid(d, '9')); a.inv(0x6e, seq, [3, 2]); a.mr(3); a.b21(0x38, 3, 'end')
        a.L('tele')
        a.c16(6, 12288); a.go('set')
        a.L('main'); a.c16(6, 12256)
        a.L('set'); a.c16(5, 16320); a.c4(8, 6)
        a.cs(2, KFLAG); a.inv(0x72, put, [1, 2, 2])
        a.L('end')
        return a.done()
    insert(c, p, R2); check(c)
    q = find(c, [0x051a, sid(d, 'pref_upscale_key')])[0]
    def R2b(base, na):
        a = S(base); a.inv(0x71, props, []); a.mro(5); a.cs(6, KFLAG); a.inv(0x72, rem, [5, 6]); return a.done()
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
    # M1 (Llei entry): viewfinder results (Llei.a != null) -> props gains / transform / neutral point
    crget = M('Landroid/hardware/camera2/CaptureResult;', 'get', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;')
    CRK = 'Landroid/hardware/camera2/CaptureResult$Key;'
    fCR = lambda n: [i for i in range(len(d.fields)) if d.fname(i) == 'Landroid/hardware/camera2/CaptureResult;->%s:%s' % (n, CRK)][0]
    KG, KT, KN = sid(d, 'AwbInfo_gains_get'), sid(d, 'AwbInfo_rgb2rgb_get'), sid(d, 'AwbInfo_IsValid')
    fLa = F('Llei;->a:Lldg;')
    m1 = {}
    def M1(base, na):
        a = S(base); a.L('t0')
        a.raw(0x54 | 0 << 8 | 4 << 12, fLa); a.b21(0x38, 0, 'end')
        a.inv(0x71, props, []); a.mro(1)
        for kn, ks in (('COLOR_CORRECTION_GAINS', KG), ('COLOR_CORRECTION_TRANSFORM', KT), ('SENSOR_NEUTRAL_COLOR_POINT', KN)):
            a.raw(0x62, fCR(kn)); a.inv(0x6e, crget, [7, 0]); a.mro(2); a.b21(0x38, 2, 'n' + kn)
            a.cs(3, ks); a.inv(0x72, put, [1, 3, 2])
            a.L('n' + kn)
        a.L('t1'); a.L('end')
        w = a.done(); m1.update(t0=a.lab['t0'], t1=a.lab['t1'], h=a.lab['end']); return w
    insert(c, 0, M1); check(c)
    c.handlers.append([[], m1['h']]); c.tries.append([m1['t0'], m1['t1'] - m1['t0'], len(c.handlers) - 1])
    c.tries.sort(key=lambda t: t[0])
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
    fix_outs(c); out[m] = c.build()

    # L2: Llei.onCaptureFailed (burst callback): log the CaptureFailure (v4)
    m = one(d, 'Llei;', 'onCaptureFailed'); c = Code(raw, d.code[m])
    q = find(c, [0x106e, M('Landroid/hardware/camera2/CaptureFailure;', 'getReason', '()I'), 0x0004])[0]
    if LOG:
        helper_call(c, q, 0, 2, 4)
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
        a.cs(2, KPREF); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'end')
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
        a.L('t1')
        a.L('end')
        w = a.done(); hinfo['t0'] = a.lab['set']; hinfo['t1'] = a.lab['t1']; hinfo['end'] = a.lab['end']; return w
    insert(c, p, Hb); check(c)
    for s_, n_, h_ in c.tries: assert s_ + n_ <= hinfo['t0'] or s_ >= hinfo['t1'], 'try overlap H'
    c.handlers.append([[], hinfo['end']]); c.tries.append([hinfo['t0'], hinfo['t1'] - hinfo['t0'], len(c.handlers) - 1])
    c.tries.sort(key=lambda t: t[0]); fix_outs(c); out[m] = c.build()

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
    m = one(d, 'Lohv;', 'k'); c = Code(raw, d.code[m])
    p = [q for q in find(c, [0x031f, T('[F'), 0x0338], n=3) if c.w[q - 6:q - 4] == [0x0362, fCR('SENSOR_DYNAMIC_BLACK_LEVEL')]]
    assert len(p) == 1, p
    p = p[0] + 2
    def M3(base, na):
        a = S(base)
        a.inv(0x71, props, []); a.mro(4); a.cs(5, KFLAG); a.inv(0x72, get, [4, 5]); a.mro(4); a.b21(0x38, 4, 'end')
        a.c4(3, 0); a.L('end'); return a.done()
    insert(c, p, M3); check(c); fix_outs(c); out[m] = c.build()

    # ---- W1: Lleu reader width check ----
    m = one(d, 'Lleu;', 'onImageAvailable'); c = Code(raw, d.code[m])
    p = find(c, [0x0313, 8192, 0x3233])[0]
    tOA = T('[Ljava/lang/Object;'); winfo = {}
    def W1(base, na):
        a = S(base); a.c16(3, 16320); a.b22(0x33, 2, 3, 'end')
        a.L('t0')
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
    fix_outs(c); out[m] = c.build()

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
        a.c16(0, 16320); a.b22(0x33, 1, 0, na(p))                             # not 16320 -> original code
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
    fe = F('Llet;->e:Landroid/media/Image;')
    def Fb(base, na):
        a = S(base)
        a.raw(0x52 | 0 << 8 | 2 << 12, fb_)                                  # iget v0, v2, b
        a.raw(0x54 | 1 << 8 | 2 << 12, fe); a.inv(0x6e, imgw, [1]); a.mr(1)
        a.b22(0x32, 0, 1, na(0))                                             # same width -> original
        a.c4(0, 0); a.raw(0x0011)                                            # return-object null
        return a.done()
    Lf = insert(c, 0, Fb); check(c)
    # getWidth on a closed Image throws: catch-all -> original code (block start + Lf)
    for s_, n_, h_ in c.tries: assert s_ >= 7, 'try overlap F'
    c.handlers.append([[], Lf]); c.tries.append([4, 3, len(c.handlers) - 1]); c.tries.sort(key=lambda t: t[0])
    fix_outs(c); out[m] = c.build()

    o = bytearray(relocate(raw, out)); fix_hdr(o)
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
        a.cs(1, s2('FULL')); a.cs(2, s2('setTemporalBinning')); a.inv(0x71, menu, [2]); a.mr(2); a.b21(0x38, 2, 'app')
        a.cs(1, s2('leica'))
        a.L('app'); a.inv(0x6e, app, [0, 1])
        a.L('end'); return a.done()
    outs2 = {}
    for name in ('SetLensValue', 'SetLensValueBack'):     # readers / the long-press ZSL selector (read + write)
        m = one(d, 'LMC/lensvalue;', name); c = Code(raw2, d.code[m])
        p = [q for q in range(len(c.w) - 1) if c.w[q] == 0x106e and c.w[q + 1] == sb_tos]; assert len(p) == 1, p
        assert c.regs == 6 and c.ins == 1
        insert(c, p[0], P); check(c); fix_outs(c); outs2[m] = c.build()
    o = bytearray(relocate(raw2, outs2))
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
    so = open(os.path.join(HERE, 'libtbin.so'), 'rb').read()
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2}, {'classes3.dex': c3, 'lib/arm64-v8a/libtbin.so': so})
    for nm, b in (('classes.dex', c1), ('classes2.dex', c2), ('classes3.dex', c3), ('libtbin.so', so)):
        print(nm, hashlib.sha256(b).hexdigest())
    print('wrote', dst)
