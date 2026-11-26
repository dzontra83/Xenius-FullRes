#!/usr/bin/env python3
"""Minimal DEX writer for XENIUS P175 classes3.dex (TemporalBinning helper).

Classes (default package, same class loader as classes.dex):
  TemporalBinning      public static Object a(Object image)   -- the only declared method (found by reflection)
  TemporalBinning$N    static { System.loadLibrary("tbin"); }  static native int b(ByteBuffer,int,int,int,ByteBuffer)

a(image): off the main thread, for a 16320-wide RAW16 Image: allocateDirect(8192*6144*2), native same-colour 2x bin
(libtbin.so), logcat 'TBIN bin ns=.. rc=..', returns an Lnns list holding one Lles plane (buffer, rowStride 16384,
pixelStride 2) for Llet.<init>; otherwise null.
"""
import struct, hashlib, zlib


def uleb(v):
    o = bytearray()
    while True:
        b = v & 0x7f; v >>= 7
        if v: o.append(b | 0x80)
        else: o.append(b); return bytes(o)


def mutf8(s):
    return s.encode('utf-8')  # ASCII only here


def shorty(t):
    return 'L' if t[0] in 'L[' else t


def parse_proto(p):  # '(Ljava/lang/Object;I)V' -> ret, [params]
    assert p[0] == '('
    i = 1; ps = []
    while p[i] != ')':
        j = i
        while p[j] == '[': j += 1
        if p[j] == 'L': j = p.index(';', j)
        ps.append(p[i:j + 1]); i = j + 1
    return p[i + 1:], ps


class DexGen:
    def __init__(self):
        self.strings = set(); self.types = set(); self.protos = set(); self.methods = set(); self.classes = []
        self.fields = set()

    def S(self, s): self.strings.add(s); return ('s', s)
    def T(self, t): self.strings.add(t); self.types.add(t); return ('t', t)
    def P(self, p):
        r, ps = parse_proto(p)
        sh = shorty(r) + ''.join(shorty(x) for x in ps)
        self.strings.add(sh); self.T(r); [self.T(x) for x in ps]
        self.protos.add(p); return ('p', p)
    def M(self, c, n, p):
        self.T(c); self.S(n); self.P(p); self.methods.add((c, n, p)); return ('m', (c, n, p))

    def Fd(self, c, n, t):
        self.T(c); self.S(n); self.T(t); self.fields.add((c, n, t)); return ('f', (c, n, t))

    def cls(self, name, sup, acc, direct):
        """direct: list of (name, proto, access, code or None). code = (regs, ins, outs, words(list with refs))"""
        self.T(name); self.T(sup)
        for n, p, a, code in direct: self.M(name, n, p)
        self.classes.append((name, sup, acc, direct))

    def build(self):
        strings = sorted(self.strings, key=lambda s: [ord(c) for c in s])
        sidx = {s: i for i, s in enumerate(strings)}
        types = sorted(self.types, key=lambda t: sidx[t]); tidx = {t: i for i, t in enumerate(types)}
        def pkey(p):
            r, ps = parse_proto(p); return (tidx[r], [tidx[x] for x in ps])
        protos = sorted(self.protos, key=pkey); pidx = {p: i for i, p in enumerate(protos)}
        methods = sorted(self.methods, key=lambda m: (tidx[m[0]], sidx[m[1]], pidx[m[2]]))
        midx = {m: i for i, m in enumerate(methods)}
        fields = sorted(self.fields, key=lambda f: (tidx[f[0]], sidx[f[1]], tidx[f[2]]))
        fidx = {f: i for i, f in enumerate(fields)}

        def res(w):
            if isinstance(w, int): return w
            k, v = w
            return {'s': sidx, 't': tidx, 'p': pidx, 'm': midx, 'f': fidx}[k][v]

        H = 0x70
        off = H
        sid_off = off; off += 4 * len(strings)
        tid_off = off; off += 4 * len(types)
        pid_off = off; off += 12 * len(protos)
        fid_off = off; off += 8 * len(fields)
        mid_off = off; off += 8 * len(methods)
        cd_off = off; off += 32 * len(self.classes)
        data_off = off
        data = bytearray()
        def here(): return data_off + len(data)
        def align4():
            while here() % 4: data.append(0)

        # type_lists (protos with params)
        align4(); tl_start = here(); tl_off = {}; ntl = 0
        for p in protos:
            r, ps = parse_proto(p)
            if not ps: continue
            align4(); tl_off[p] = here(); ntl += 1
            data.extend(struct.pack('<I', len(ps)) + b''.join(struct.pack('<H', tidx[x]) for x in ps))
        # code items
        align4(); code_start = here(); ncode = 0; code_off = {}
        for name, sup, acc, direct in self.classes:
            for n, p, a, code in direct:
                if code is None: continue
                align4(); code_off[(name, n, p)] = here(); ncode += 1
                regs, ins, outs, words = code[:4]
                tries = code[4] if len(code) > 4 else []
                ws = [res(w) for w in words]
                data.extend(struct.pack('<HHHHII', regs, ins, outs, len(tries), 0, len(ws)))
                data.extend(struct.pack('<%dH' % len(ws), *ws))
                if tries:
                    if len(ws) % 2: data.extend(b'\0\0')
                    hl = bytearray(uleb(len(tries))); hoff = []
                    for st, cnt, h in tries:
                        hoff.append(len(hl)); hl += b'\x00' + uleb(h)      # sleb(0): catch-all only
                    for (st, cnt, h), ho in zip(tries, hoff): data.extend(struct.pack('<IHH', st, cnt, ho))
                    data.extend(hl)
        # string data
        sd_start = here(); sd_off = []
        for s in strings:
            sd_off.append(here()); data.extend(uleb(len(s)) + mutf8(s) + b'\0')
        # class data
        cdata_start = here(); cdata_off = []
        for name, sup, acc, direct in self.classes:
            cdata_off.append(here())
            ms = sorted(direct, key=lambda d: midx[(name, d[0], d[1])])
            data.extend(uleb(0) + uleb(0) + uleb(len(ms)) + uleb(0))
            prev = 0
            for n, p, a, code in ms:
                mi = midx[(name, n, p)]
                data.extend(uleb(mi - prev) + uleb(a) + uleb(code_off.get((name, n, p), 0))); prev = mi
        # map
        align4(); map_off = here()
        items = [(0x0000, 1, 0), (0x0001, len(strings), sid_off), (0x0002, len(types), tid_off),
                 (0x0003, len(protos), pid_off)] + ([(0x0004, len(fields), fid_off)] if fields else []) + [(0x0005, len(methods), mid_off), (0x0006, len(self.classes), cd_off)]
        if ntl: items.append((0x1001, ntl, tl_start))
        items += [(0x2001, ncode, code_start), (0x2002, len(strings), sd_start), (0x2000, len(self.classes), cdata_start),
                  (0x1000, 1, map_off)]
        data.extend(struct.pack('<I', len(items)))
        for t, n, o in items: data.extend(struct.pack('<HHII', t, 0, n, o))
        total = data_off + len(data)

        out = bytearray(total)
        for i, s in enumerate(strings): struct.pack_into('<I', out, sid_off + 4 * i, sd_off[i])
        for i, t in enumerate(types): struct.pack_into('<I', out, tid_off + 4 * i, sidx[t])
        for i, p in enumerate(protos):
            r, ps = parse_proto(p)
            sh = shorty(r) + ''.join(shorty(x) for x in ps)
            struct.pack_into('<III', out, pid_off + 12 * i, sidx[sh], tidx[r], tl_off.get(p, 0))
        for i, (c, n, p) in enumerate(methods): struct.pack_into('<HHI', out, mid_off + 8 * i, tidx[c], pidx[p], sidx[n])
        for i, (c, n, t) in enumerate(fields): struct.pack_into('<HHI', out, fid_off + 8 * i, tidx[c], tidx[t], sidx[n])
        for i, (name, sup, acc, direct) in enumerate(self.classes):
            struct.pack_into('<8I', out, cd_off + 32 * i, tidx[name], acc, tidx[sup], 0, 0xffffffff, 0, cdata_off[i], 0)
        out[data_off:] = data
        out[0:8] = b'dex\n035\0'
        struct.pack_into('<I', out, 32, total); struct.pack_into('<I', out, 36, H); struct.pack_into('<I', out, 40, 0x12345678)
        struct.pack_into('<II', out, 44, 0, 0)        # link
        struct.pack_into('<I', out, 52, map_off)
        struct.pack_into('<II', out, 56, len(strings), sid_off)
        struct.pack_into('<II', out, 64, len(types), tid_off)
        struct.pack_into('<II', out, 72, len(protos), pid_off)
        struct.pack_into('<II', out, 80, len(fields), fid_off if fields else 0)
        struct.pack_into('<II', out, 88, len(methods), mid_off)
        struct.pack_into('<II', out, 96, len(self.classes), cd_off)
        struct.pack_into('<II', out, 104, len(data), data_off)
        out[12:32] = hashlib.sha1(out[32:]).digest()
        struct.pack_into('<I', out, 8, zlib.adler32(bytes(out[12:])) & 0xffffffff)
        return bytes(out)


# ---------------- assembler ----------------
class A:
    def __init__(self): self.w = []; self.lab = {}; self.fix = []
    def L(self, n): self.lab[n] = len(self.w)
    def pc(self): return len(self.w)
    def inv(self, op, m, regs):
        g = regs[4] if len(regs) == 5 else 0; p = 0
        for i, r in enumerate(regs[:4]): p |= r << (4 * i)
        self.w += [op | len(regs) << 12 | g << 8, m, p]
    def mr(self, a): self.w += [0x0a | a << 8]
    def mrw(self, a): self.w += [0x0b | a << 8]
    def mro(self, a): self.w += [0x0c | a << 8]
    def cs(self, a, s): self.w += [0x1a | a << 8, s]
    def c4(self, a, v): self.w += [0x12 | a << 8 | (v & 15) << 12]
    def c16(self, a, v): self.w += [0x13 | a << 8, v & 0xffff]
    def c32(self, a, v): self.w += [0x14 | a << 8, v & 0xffff, (v >> 16) & 0xffff]
    def t21(self, op, a, t): self.w += [op | a << 8, t]           # check-cast/new-instance/const-class
    def iof(self, a, b, t): self.w += [0x20 | a << 8 | b << 12, t]  # instance-of
    def b21(self, op, a, t): self.fix.append((len(self.w), t)); self.w += [op | a << 8, 0]
    def b22(self, op, a, b, t): self.fix.append((len(self.w), t)); self.w += [op | a << 8 | b << 12, 0]
    def go(self, t): self.fix.append((len(self.w), t)); self.w += [0x29, 0]   # goto/16
    def raw(self, *x): self.w += list(x)
    def done(self):
        for at, t in self.fix:
            off = self.lab[t] - at; assert -32768 <= off < 32768; self.w[at + 1] = off & 0xffff
        return self.w


def build_classes3():
    g = DexGen()
    OBJ = 'Ljava/lang/Object;'; STR = 'Ljava/lang/String;'
    IMG = 'Landroid/media/Image;'; PL = 'Landroid/media/Image$Plane;'; BB = 'Ljava/nio/ByteBuffer;'
    SB = 'Ljava/lang/StringBuilder;'; FILE = 'Ljava/io/File;'; FW = 'Ljava/io/FileWriter;'
    LCL = 'LTemporalBinning$L;'; NCL = 'LTemporalBinning$N;'
    myl = g.M('Landroid/os/Looper;', 'myLooper', '()Landroid/os/Looper;')
    mainl = g.M('Landroid/os/Looper;', 'getMainLooper', '()Landroid/os/Looper;')
    gw = g.M(IMG, 'getWidth', '()I'); gh = g.M(IMG, 'getHeight', '()I')
    gp = g.M(IMG, 'getPlanes', '()[' + PL)
    grs = g.M(PL, 'getRowStride', '()I'); gbuf = g.M(PL, 'getBuffer', '()' + BB)
    alloc = g.M(BB, 'allocateDirect', '(I)' + BB)
    nano = g.M('Ljava/lang/System;', 'nanoTime', '()J'); now = g.M('Ljava/lang/System;', 'currentTimeMillis', '()J')
    loadl = g.M('Ljava/lang/System;', 'loadLibrary', '(' + STR + ')V')
    nb = g.M(NCL, 'b', '(' + BB + 'III' + BB + ')I')
    ll = g.M(LCL, 'l', '(' + STR + ')V')
    les = g.M('Lles;', '<init>', '(' + BB + 'III)V')
    nnn = g.M('Lnnn;', '<init>', '()V'); nng = g.M('Lnnn;', 'g', '(' + OBJ + ')V'); nnf = g.M('Lnnn;', 'f', '()Lnns;')
    sbi = g.M(SB, '<init>', '()V'); sbs = g.M(SB, 'append', '(' + STR + ')' + SB)
    sbo = g.M(SB, 'append', '(' + OBJ + ')' + SB)
    sbj = g.M(SB, 'append', '(J)' + SB); sbI = g.M(SB, 'append', '(I)' + SB); sbt = g.M(SB, 'toString', '()' + STR)
    pubdir = g.M('Landroid/os/Environment;', 'getExternalStoragePublicDirectory', '(' + STR + ')' + FILE)
    finit = g.M(FILE, '<init>', '(' + FILE + STR + ')V'); fwinit = g.M(FW, '<init>', '(' + FILE + 'Z)V')
    wr = g.M('Ljava/io/Writer;', 'write', '(' + STR + ')V'); wcl = g.M('Ljava/io/Writer;', 'close', '()V')
    tIMG = g.T(IMG); tSB = g.T(SB); tLES = g.T('Lles;'); tNNN = g.T('Lnnn;'); tSTR = g.T(STR)
    tFILE = g.T(FILE); tFW = g.T(FW)
    S = g.S

    # ---- L.l(String): append "<ms> TBIN <s>\n" to Download/merge.txt, never throws ----
    a = A()
    a.L('t0')
    a.cs(0, S('Download')); a.inv(0x71, pubdir, [0]); a.mro(0)
    a.t21(0x22, 1, tFILE); a.cs(2, S('merge.txt')); a.inv(0x70, finit, [1, 0, 2])
    a.t21(0x22, 0, tFW); a.c4(2, 1); a.inv(0x70, fwinit, [0, 1, 2])
    a.t21(0x22, 1, tSB); a.inv(0x70, sbi, [1])
    a.inv(0x71, now, []); a.mrw(2); a.inv(0x6e, sbj, [1, 2, 3])
    a.cs(2, S(' TBIN ')); a.inv(0x6e, sbs, [1, 2])
    a.inv(0x6e, sbs, [1, 4])
    a.cs(2, S('\n')); a.inv(0x6e, sbs, [1, 2])
    a.inv(0x6e, sbt, [1]); a.mro(1)
    a.inv(0x6e, wr, [0, 1]); a.inv(0x6e, wcl, [0])
    a.L('t1')
    a.raw(0x000e)
    a.L('h'); a.raw(0x000e)
    w = a.done()
    code_l = (5, 1, 4, w, [(a.lab['t0'], a.lab['t1'] - a.lab['t0'], a.lab['h'])])
    import os
    if os.environ.get('TBLOG', '0') != '1':
        code_l = (5, 1, 0, [0x000e])                                    # quiet build: l() does nothing

    # ---- a(Object): v12 = arg ----
    a = A()
    def sb_new(r): a.t21(0x22, r, tSB); a.inv(0x70, sbi, [r])
    def sb_s(r, t, s): a.cs(t, S(s)); a.inv(0x6e, sbs, [r, t])
    def log_sb(r): a.inv(0x6e, sbt, [r]); a.mro(r); a.inv(0x71, ll, [r])
    CF = 'Landroid/hardware/camera2/CaptureFailure;'
    tCF = g.T(CF); cfr = g.M(CF, 'getReason', '()I'); cff = g.M(CF, 'getFrameNumber', '()J')
    cfw = g.M(CF, 'wasImageCaptured', '()Z'); sbz = g.M(SB, 'append', '(Z)' + SB)
    getp = g.M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    mget = g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ)
    mput = g.M('Ljava/util/Map;', 'put', '(' + OBJ + OBJ + ')' + OBJ)
    mrem = g.M('Ljava/util/Map;', 'remove', '(' + OBJ + ')' + OBJ)
    INT = 'Ljava/lang/Integer;'; tINT = g.T(INT); tOA = g.T('[' + OBJ)
    ivl = g.M(INT, 'intValue', '()I'); ivo = g.M(INT, 'valueOf', '(I)' + INT)
    SES = 'Landroid/hardware/camera2/CameraCaptureSession;'; REQ = 'Landroid/hardware/camera2/CaptureRequest;'
    CB = 'Landroid/hardware/camera2/CameraCaptureSession$CaptureCallback;'; HND = 'Landroid/os/Handler;'
    cap = g.M(SES, 'capture', '(' + REQ + CB + HND + ')I')
    tSES, tREQ, tCB, tHND = g.T(SES), g.T(REQ), g.T(CB), g.T(HND)
    a.L('t0')
    # ---- Object[5] {session, request, callback, handler, Integer n}: 200 MP -> queue n-1 one-by-one captures ----
    a.iof(0, 12, tOA); a.b21(0x38, 0, 'st')
    a.t21(0x1f, 12, tOA)
    a.inv(0x71, getp, []); a.mro(1)
    a.cs(2, S('TemporalBinning')); a.inv(0x72, mget, [1, 2]); a.mro(2); a.b21(0x38, 2, 'null')
    a.c4(2, 4); a.raw(0x46 | 3 << 8, 12 | 2 << 8); a.t21(0x1f, 3, tINT); a.inv(0x6e, ivl, [3]); a.mr(3)   # v3 = n
    a.c4(4, 1); a.b22(0x37, 3, 4, 'null')                              # n <= 1 -> nothing to queue
    a.raw(0xd8 | 3 << 8, 3 | 0xff << 8)                                # add-int/lit8 v3, v3, -1
    a.inv(0x71, ivo, [3]); a.mro(5); a.raw(0x4d | 5 << 8, 12 | 2 << 8)  # aput-object v5, v12, v2(=4)
    a.cs(2, S('TBQ')); a.inv(0x72, mput, [1, 2, 12])
    sb_new(6); sb_s(6, 7, 'queue '); a.inv(0x6e, sbI, [6, 3]); log_sb(6)
    a.inv(0x71, ivo, [4]); a.mro(0); a.raw(0x0011)                     # return Integer(1)
    a.L('st')
    a.iof(0, 12, tSTR); a.b21(0x38, 0, 'cf')
    a.t21(0x1f, 12, tSTR); a.inv(0x71, ll, [12])
    # frame arrived: send the next queued capture
    a.inv(0x71, getp, []); a.mro(1)
    a.cs(2, S('TBQ')); a.inv(0x72, mget, [1, 2]); a.mro(12); a.b21(0x38, 12, 'null')
    a.t21(0x1f, 12, tOA)
    a.c4(2, 4); a.raw(0x46 | 3 << 8, 12 | 2 << 8); a.t21(0x1f, 3, tINT); a.inv(0x6e, ivl, [3]); a.mr(3)
    a.b21(0x3d, 3, 'qdone')                                             # if-lez v3 -> remove
    a.raw(0xd8 | 3 << 8, 3 | 0xff << 8)
    a.inv(0x71, ivo, [3]); a.mro(5); a.raw(0x4d | 5 << 8, 12 | 2 << 8)
    a.b21(0x39, 3, 'send'); a.cs(2, S('TBQ')); a.inv(0x72, mrem, [1, 2])
    a.L('send')
    a.c4(2, 0); a.raw(0x46 | 4 << 8, 12 | 2 << 8); a.t21(0x1f, 4, tSES)
    a.c4(2, 1); a.raw(0x46 | 5 << 8, 12 | 2 << 8); a.t21(0x1f, 5, tREQ)
    a.c4(2, 2); a.raw(0x46 | 6 << 8, 12 | 2 << 8); a.t21(0x1f, 6, tCB)
    a.c4(2, 3); a.raw(0x46 | 7 << 8, 12 | 2 << 8); a.t21(0x1f, 7, tHND)
    a.inv(0x6e, cap, [4, 5, 6, 7])
    sb_new(6); sb_s(6, 7, 'next left='); a.inv(0x6e, sbI, [6, 3]); log_sb(6)
    a.go('null')
    a.L('qdone'); a.cs(2, S('TBQ')); a.inv(0x72, mrem, [1, 2]); a.go('null')
    a.L('cf')
    a.iof(0, 12, tCF); a.b21(0x38, 0, 'im0')
    a.t21(0x1f, 12, tCF)
    sb_new(6); sb_s(6, 7, 'fail reason=')
    a.inv(0x6e, cfr, [12]); a.mr(0); a.inv(0x6e, sbI, [6, 0])
    sb_s(6, 7, ' frame='); a.inv(0x6e, cff, [12]); a.mrw(8); a.inv(0x6e, sbj, [6, 8, 9])
    sb_s(6, 7, ' imageCaptured='); a.inv(0x6e, cfw, [12]); a.mr(0); a.inv(0x6e, sbz, [6, 0])
    log_sb(6); a.go('null')
    a.L('im0')
    a.iof(0, 12, g.T('Lljm;')); a.b21(0x38, 0, 'im1')
    CR = 'Landroid/hardware/camera2/CaptureResult;'; KEY = 'Landroid/hardware/camera2/CaptureResult$Key;'
    ld = g.M('Lljm;', 'd', '(' + KEY + ')' + OBJ)
    kname = g.M(KEY, 'getName', '()' + STR)
    atf = g.M('Ljava/util/Arrays;', 'toString', '([F)' + STR); ati = g.M('Ljava/util/Arrays;', 'toString', '([I)' + STR)
    tF = g.T('[F'); tI = g.T('[I')
    sb_new(6); sb_s(6, 7, 'meta')
    for kn in ('SENSOR_TIMESTAMP', 'SENSOR_SENSITIVITY', 'SENSOR_EXPOSURE_TIME', 'CONTROL_POST_RAW_SENSITIVITY_BOOST',
               'SENSOR_DYNAMIC_BLACK_LEVEL', 'SENSOR_DYNAMIC_WHITE_LEVEL', 'SCALER_CROP_REGION', 'SHADING_MODE',
               'STATISTICS_LENS_SHADING_MAP_MODE', 'SENSOR_NEUTRAL_COLOR_POINT', 'COLOR_CORRECTION_GAINS',
               'SENSOR_PIXEL_MODE'):
        fk = g.Fd(CR, kn, KEY)
        a.raw(0x62 | 0 << 8, fk)                                    # sget-object v0, key
        sb_s(6, 7, ' ' + kn + '=')
        a.inv(0x72, ld, [12, 0]); a.mro(1)
        lab = 'k' + kn
        a.iof(2, 1, tF); a.b21(0x38, 2, lab + 'i')
        a.t21(0x1f, 1, tF); a.inv(0x71, atf, [1]); a.mro(1); a.go(lab)
        a.L(lab + 'i'); a.iof(2, 1, tI); a.b21(0x38, 2, lab)
        a.t21(0x1f, 1, tI); a.inv(0x71, ati, [1]); a.mro(1)
        a.L(lab); a.inv(0x6e, sbo, [6, 1])
    a.inv(0x71, getp, []); a.mro(0)
    for k in ('TemporalBinning', 'AwbInfo_gains_get', 'AwbInfo_rgb2rgb_get'):
        sb_s(6, 7, ' P[' + k + ']='); a.cs(1, S(k)); a.inv(0x72, mget, [0, 1]); a.mro(1); a.inv(0x6e, sbo, [6, 1])
    log_sb(6); a.go('null')
    a.L('im1')
    a.iof(0, 12, tIMG); a.b21(0x39, 0, 'img')
    sb_new(6); sb_s(6, 7, 'obj '); a.inv(0x6e, sbo, [6, 12]); log_sb(6); a.go('null')
    a.L('img')
    a.t21(0x1f, 12, tIMG)
    a.inv(0x6e, gw, [12]); a.mr(2); a.inv(0x6e, gh, [12]); a.mr(3)
    a.inv(0x71, myl, []); a.mro(0); a.inv(0x71, mainl, []); a.mro(1)
    sb_new(6); sb_s(6, 7, 'a w='); a.inv(0x6e, sbI, [6, 2]); sb_s(6, 7, ' h='); a.inv(0x6e, sbI, [6, 3])
    sb_s(6, 7, ' thread='); a.inv(0x6e, sbo, [6, 0]); log_sb(6)
    a.b22(0x32, 0, 1, 'null')                                   # main thread -> no binning
    a.c16(4, 16320); a.b22(0x33, 2, 4, 'null')
    a.inv(0x6e, gp, [12]); a.mro(0); a.c4(1, 0); a.raw(0x0046, 0x0100)
    a.inv(0x6e, grs, [0]); a.mr(1); a.inv(0x6e, gbuf, [0]); a.mro(0)
    a.c32(4, 100663296); a.inv(0x71, alloc, [4]); a.mro(4)
    a.inv(0x71, nano, []); a.mrw(8)
    a.inv(0x71, nb, [0, 1, 2, 3, 4]); a.mr(5)
    a.inv(0x71, nano, []); a.mrw(10)
    a.raw(0x00bc | 10 << 8 | 8 << 12)
    sb_new(6); sb_s(6, 7, 'bin ns='); a.inv(0x6e, sbj, [6, 10, 11])
    sb_s(6, 7, ' rs='); a.inv(0x6e, sbI, [6, 1])
    sb_s(6, 7, ' ret='); a.inv(0x6e, sbI, [6, 5]); log_sb(6)
    a.raw(0x00d5 | 5 << 8 | 5 << 12, 0xff)                      # and-int/lit16 v5, v5, 0xff
    a.b21(0x39, 5, 'null')
    a.t21(0x22, 0, tLES); a.c16(1, 16384); a.c4(2, 2); a.c4(3, 0)
    a.inv(0x70, les, [0, 4, 1, 2, 3])
    a.t21(0x22, 1, tNNN); a.inv(0x70, nnn, [1]); a.inv(0x6e, nng, [1, 0])
    a.inv(0x6e, nnf, [1]); a.mro(0)
    a.L('t1')
    a.raw(0x0011)
    a.L('null'); a.c4(0, 0); a.raw(0x0011)
    a.L('h')
    a.raw(0x000d | 0 << 8)                                      # move-exception v0
    sb_new(6); sb_s(6, 7, 'err '); a.inv(0x6e, sbo, [6, 0]); log_sb(6)
    a.c4(0, 0); a.raw(0x0011)
    w = a.done()
    code_a = (13, 1, 5, w, [(a.lab['t0'], a.lab['t1'] - a.lab['t0'], a.lab['h'])])

    clinit = (1, 0, 1, [0x1a | 0 << 8, S('tbin')] + [0x1071, loadl, 0] + [0x000e])

    g.cls('LTemporalBinning;', OBJ, 0x1, [('a', '(' + OBJ + ')' + OBJ, 0x9, code_a)])
    g.cls(NCL, OBJ, 0x1, [('<clinit>', '()V', 0x10008, clinit), ('b', '(' + BB + 'III' + BB + ')I', 0x109, None)])
    g.cls(LCL, OBJ, 0x1, [('l', '(' + STR + ')V', 0x9, code_l)])
    return g.build()


if __name__ == '__main__':
    import sys
    b = build_classes3(); open(sys.argv[1], 'wb').write(b); print(len(b), 'bytes')
