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
        self.fields = set(); self.ifields = {}

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

    def cls(self, name, sup, acc, direct, virtual=(), ifaces=(), ifields=()):
        """direct/virtual: list of (name, proto, access, code or None). code = (regs, ins, outs, words(list with refs))"""
        self.T(name); self.T(sup); [self.T(i) for i in ifaces]
        for n, p, a, code in list(direct) + list(virtual): self.M(name, n, p)
        for n, t in ifields: self.Fd(name, n, t)
        self.ifields[name] = list(ifields)
        self.classes.append((name, sup, acc, list(direct), list(virtual), list(ifaces)))

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
        if_off = {}
        for name, sup, acc, direct, virtual, ifaces in self.classes:
            if not ifaces: continue
            align4(); if_off[name] = here(); ntl += 1
            data.extend(struct.pack('<I', len(ifaces)) + b''.join(struct.pack('<H', tidx[x]) for x in ifaces))
        # code items
        align4(); code_start = here(); ncode = 0; code_off = {}
        for name, sup, acc, direct, virtual, ifaces in self.classes:
            for n, p, a, code in direct + virtual:
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
        for name, sup, acc, direct, virtual, ifaces in self.classes:
            cdata_off.append(here())
            ms = sorted(direct, key=lambda d: midx[(name, d[0], d[1])])
            vs = sorted(virtual, key=lambda d: midx[(name, d[0], d[1])])
            ifs = sorted(fidx[(name, n, t)] for n, t in self.ifields.get(name, []))
            data.extend(uleb(0) + uleb(len(ifs)) + uleb(len(ms)) + uleb(len(vs)))
            prev = 0
            for fi in ifs: data.extend(uleb(fi - prev) + uleb(0x1)); prev = fi
            for lst in (ms, vs):
                prev = 0
                for n, p, a, code in lst:
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
        for i, (name, sup, acc, direct, virtual, ifaces) in enumerate(self.classes):
            struct.pack_into('<8I', out, cd_off + 32 * i, tidx[name], acc, tidx[sup], if_off.get(name, 0), 0xffffffff, 0, cdata_off[i], 0)
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
    def invr(self, op, m, first, n): self.w += [op | n << 8, m, first]
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


FOCUS_L = ['AF Auto', 'Inf', '5 m', '3 m', '2 m', '1.5 m', '1 m', '70 cm', '50 cm', '40 cm', '30 cm', '25 cm', '20 cm', '15 cm', '10 cm']
FOCUS_DPT = [0.0, 0.2, 1 / 3, 0.5, 2 / 3, 1.0, 1 / 0.7, 2.0, 2.5, 1 / 0.3, 4.0, 5.0, 1 / 0.15, 10.0]


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
    nb = g.M(NCL, 'b', '(' + BB + 'III' + BB + 'II)I')
    nw = g.M(NCL, 'w', '()V'); nf = g.M(NCL, 'f', '()I')
    nq = g.M(NCL, 'q', '(' + BB + 'III' + BB + ')I'); na_ = g.M(NCL, 'a', '()' + BB); nr = g.M(NCL, 'r', '(' + BB + ')I')
    WCL = 'LTemporalBinning$W;'; TH = 'Ljava/lang/Thread;'; RUN = 'Ljava/lang/Runnable;'
    winit = g.M(WCL, '<init>', '()V'); oinit = g.M(OBJ, '<init>', '()V')
    thinit = g.M(TH, '<init>', '(' + RUN + ')V'); thstart = g.M(TH, 'start', '()V'); thjoin = g.M(TH, 'join', '()V')
    rtget = g.M('Ljava/lang/Runtime;', 'getRuntime', '()Ljava/lang/Runtime;'); rtcpu = g.M('Ljava/lang/Runtime;', 'availableProcessors', '()I')
    RGB = 'Landroid/hardware/camera2/params/RggbChannelVector;'
    gred = g.M(RGB, 'getRed', '()F'); gblue = g.M(RGB, 'getBlue', '()F')
    tW = g.T(WCL); tTH = g.T(TH); tTHA = g.T('[' + TH); tRGB = g.T(RGB)
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
    PVW = os.environ.get('PVW', '0') == '1'; SUBTRY = []
    PACE = int(os.environ.get('PACE', '6'))                          # 50 MP frames in flight (0 = whole burst)
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
    UEH = 'Ljava/lang/Thread$UncaughtExceptionHandler;'; UCL = 'LTemporalBinning$U;'
    lm = g.M(LCL, 'm', '()' + STR)
    if __import__('os').environ.get('TBLOG', '0') == '1':   # crash catcher: once per process
        a.inv(0x71, getp, []); a.mro(1); a.cs(2, S('TBUEH')); a.inv(0x72, mget, [1, 2]); a.mro(0)
        a.b21(0x39, 0, 'uehok')
        a.inv(0x71, g.M('Ljava/lang/Thread;', 'getDefaultUncaughtExceptionHandler', '()' + UEH), []); a.mro(0)
        a.b21(0x39, 0, 'uehput'); a.raw(0x07 | 0 << 8 | 2 << 12)        # no previous -> marker string
        a.L('uehput'); a.inv(0x72, mput, [1, 2, 0])
        a.t21(0x22, 3, g.T(UCL)); a.inv(0x70, g.M(UCL, '<init>', '()V'), [3])
        a.inv(0x71, g.M('Ljava/lang/Thread;', 'setDefaultUncaughtExceptionHandler', '(' + UEH + ')V'), [3])
        sb_new(6); sb_s(6, 7, 'start '); a.inv(0x71, lm, []); a.mro(7); a.inv(0x6e, sbs, [6, 7]); log_sb(6)
        a.L('uehok')
    # ---- quad 50 MP main (native sensor mode 3), marker props 'quadTo' set by the session build ----
    REM3 = __import__('os').environ.get('NO200', '1') == '1' and __import__('os').environ.get('REM3', '1') == '1'
    QKEY = S('quadTo'); BLD = 'Landroid/hardware/camera2/CaptureRequest$Builder;'; RKEY = 'Landroid/hardware/camera2/CaptureRequest$Key;'
    # CaptureRequest.Builder (Llel.h, RES on + Leica off + camera 3): vivo.control.forceSensorMode = {3}
    # ---- diagnostic: GCam's ZSL frame config object (Ldug, from Ldvm.G) -> dump its fields ----
    a.iof(0, 12, g.T('Ldug;')); a.b21(0x38, 0, 'dg0')
    FLD = 'Ljava/lang/reflect/Field;'
    sb_new(6); sb_s(6, 7, 'zsl Ldug ')
    a.inv(0x6e, g.M(OBJ, 'getClass', '()Ljava/lang/Class;'), [12]); a.mro(1)
    a.inv(0x6e, g.M('Ljava/lang/Class;', 'getDeclaredFields', '()[' + FLD), [1]); a.mro(1)
    a.raw(0x21 | 2 << 8 | 1 << 12); a.c4(3, 0)                                   # array-length v2, v1
    a.L('dgl'); a.b22(0x35, 3, 2, 'dgd')                                           # if-ge v3, v2
    a.raw(0x46 | 4 << 8, 1 | 3 << 8)                                               # aget-object v4, v1, v3
    a.c4(5, 1); a.inv(0x6e, g.M(FLD, 'setAccessible', '(Z)V'), [4, 5])
    a.inv(0x6e, g.M(FLD, 'getName', '()' + STR), [4]); a.mro(5); a.inv(0x6e, sbs, [6, 5]); sb_s(6, 7, '=')
    a.inv(0x6e, g.M(FLD, 'get', '(' + OBJ + ')' + OBJ), [4, 12]); a.mro(5); a.inv(0x6e, sbo, [6, 5]); sb_s(6, 7, ' ')
    a.raw(0xd8 | 3 << 8, 3 | 1 << 8); a.go('dgl')                                  # add-int/lit8 v3, v3, 1
    a.L('dgd'); log_sb(6); a.go('null')
    a.L('dg0')
    a.iof(0, 12, g.T(BLD)); a.b21(0x38, 0, 'qb0')
    a.t21(0x1f, 12, g.T(BLD))
    a.inv(0x71, getp, []); a.mro(5); a.cs(1, S('TBRTN')); a.inv(0x72, mrem, [5, 1])   # new shot: retry counter
    a.cs(1, S('TBQ')); a.inv(0x72, mrem, [5, 1])                                      # new shot: no stale paced queue
    a.cs(1, S('TBramp')); a.inv(0x72, mrem, [5, 1])                                   # P287: no stale warm-up ramp
    a.cs(1, S('nightS')); a.inv(0x72, mrem, [5, 1])                                   # P261: new shot: no night scale
    a.cs(1, S('TBNOIS')); a.inv(0x72, mrem, [5, 1])
    a.cs(1, S('getWidth')); a.inv(0x71, g.M('LMC/pref;', 'MenuValue', '(' + STR + ')I'), [1]); a.mr(1)   # P272: RES button 25 MP
    a.b21(0x38, 1, 'r25off'); a.cs(1, S('TB25')); a.inv(0x72, mput, [5, 1, 1]); a.go('r25end')
    a.L('r25off'); a.cs(1, S('TB25')); a.inv(0x72, mrem, [5, 1])
    a.L('r25end')
    a.cs(1, S('TBTAG')); a.inv(0x72, mrem, [5, 1])                                       # P280: no remosaic tag yet
    a.inv(0x71, g.M('LTBGyro;', 's', '()V'), [])                                         # P277: steady? -> 'TBlong'
    a.inv(0x71, getp, []); a.mro(5)
    # Motion / manual shutter-ISO: every non-ZSL HDR+ burst (50 MP, and 12 MP Night Sight / Enhanced)
    # ---- Motion (the LDR button, pref 'pref_enable_ldr_key'): exposure <= MOTEXP ns, ISO raised to keep the same
    #      exposure x ISO (ISO capped at MOTISO, then exposure = total / MOTISO); quad allowed up to MOTQISO ----
    CRQ = 'Landroid/hardware/camera2/CaptureRequest;'; LNG = 'Ljava/lang/Long;'
    MOTEXP = int(__import__('os').environ.get('MOTEXP', '4000000')); MOTISO = int(__import__('os').environ.get('MOTISO', '3200'))
    if __import__('os').environ.get('FREEZEAF', '1') == '1':
        # freeze focus for the burst: continuous AF (3 video / 4 picture) keeps scanning and moving the lens
        # between burst frames on this HAL; AUTO without a trigger holds the lens where the viewfinder AF left it
        INTG = 'Ljava/lang/Integer;'
        a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'CONTROL_AF_MODE', RKEY))
        a.inv(0x6e, g.M(BLD, 'get', '(' + RKEY + ')' + OBJ), [12, 1]); a.mro(2)
        a.iof(3, 2, g.T(INTG)); a.b21(0x38, 3, 'frz0'); a.t21(0x1f, 2, g.T(INTG))
        a.inv(0x6e, g.M(INTG, 'intValue', '()I'), [2]); a.mr(2)
        a.c4(3, 3); a.b22(0x34, 2, 3, 'frz0'); a.c4(3, 5); a.b22(0x35, 2, 3, 'frz0')
        a.c4(2, 1); a.inv(0x71, ivo, [2]); a.mro(2); a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 2])
        a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'CONTROL_AF_TRIGGER', RKEY))
        a.c4(2, 0); a.inv(0x71, ivo, [2]); a.mro(2); a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 2])
        sb_new(2); sb_s(2, 1, 'AF frozen for burst'); log_sb(2)
        a.L('frz0')
    if __import__('os').environ.get('OISB', 'copy') == 'off':
        # P238 (test): OIS off for the 50 MP burst ('quadTo' set). The burst request otherwise copies the
        # viewfinder's OIS mode (P158B); the remaining 6-14 px viewfinder jump when live view returns may be the
        # OIS lens shift re-centring after the sensor mode switch.
        a.inv(0x71, getp, []); a.mro(2); a.cs(1, S('quadTo')); a.inv(0x72, mget, [2, 1]); a.mro(2)
        a.b21(0x38, 2, 'ois0')
        a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'LENS_OPTICAL_STABILIZATION_MODE', RKEY))
        a.c4(2, 0); a.inv(0x71, ivo, [2]); a.mro(2); a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 2])
        sb_new(2); sb_s(2, 1, 'OIS off for burst'); log_sb(2)
        a.L('ois0')
    a.c16(6, int(__import__('os').environ.get('QISO', '32767')))
    a.cs(1, S('pref_enable_ldr_key')); a.inv(0x71, g.M('LMC/pref;', 'MenuValue', '(' + STR + ')I'), [1]); a.mr(1)
    a.b21(0x38, 1, 'lng')

    # manual focus (wheel 'pref_motion_af_key'): 0 auto, i -> FOCUS_DPT[i-1] diopters, AF off for the burst
    MS0 = g.M('LMC/pref;', 'MenuValue', '(' + STR + ')I')
    a.cs(1, S('pref_motion_af_key')); a.inv(0x71, MS0, [1]); a.mr(1); a.b21(0x38, 1, 'maf0')
    for i, dp in enumerate(FOCUS_DPT, 1):
        a.c16(2, i); a.b22(0x33, 1, 2, 'mafn%d' % i)
        a.c32(3, struct.unpack('<I', struct.pack('<f', dp))[0]); a.go('mafs'); a.L('mafn%d' % i)
    a.go('maf0')
    a.L('mafs')
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'CONTROL_AF_MODE', RKEY)); a.c4(2, 0); a.inv(0x71, ivo, [2]); a.mro(2)
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 2])
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'LENS_FOCUS_DISTANCE', RKEY))
    a.inv(0x71, g.M('Ljava/lang/Float;', 'valueOf', '(F)Ljava/lang/Float;'), [3]); a.mro(2)
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 2])
    sb_new(2); sb_s(2, 1, 'manual focus dpt='); a.inv(0x6e, g.M(SB, 'append', '(F)' + SB), [2, 3]); log_sb(2)
    a.L('maf0')
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_EXPOSURE_TIME', RKEY))
    a.inv(0x6e, g.M(BLD, 'get', '(' + RKEY + ')' + OBJ), [12, 1]); a.mro(2)
    a.iof(3, 2, g.T(LNG)); a.b21(0x38, 3, 'motna')
    a.t21(0x1f, 2, g.T(LNG)); a.inv(0x6e, g.M(LNG, 'longValue', '()J'), [2]); a.mrw(8)          # v8:v9 = exposure
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_SENSITIVITY', RKEY))
    a.inv(0x6e, g.M(BLD, 'get', '(' + RKEY + ')' + OBJ), [12, 1]); a.mro(2)
    a.iof(3, 2, tINT); a.b21(0x38, 3, 'motna')
    a.t21(0x1f, 2, tINT); a.inv(0x6e, ivl, [2]); a.mr(4)                                         # v4 = ISO
    # manual shutter / ISO (long-press on Motion): 'pref_motion_ss_key' 0 auto, i -> 500000 << (i-1) ns (1/2000 .. 1/4 s);
    # 'pref_motion_iso_key' 0 auto, i -> 50 << (i-1) (50 .. 6400). One auto: it keeps exposure x ISO. Both auto: Motion cap.
    MOTQ = int(__import__('os').environ.get('MOTQISO', '32767'))
    MS = g.M('LMC/pref;', 'MenuValue', '(' + STR + ')I')
    a.cs(1, S('pref_motion_ss_key')); a.inv(0x71, MS, [1]); a.mr(3)                             # v3 = shutter index
    a.cs(1, S('pref_motion_iso_key')); a.inv(0x71, MS, [1]); a.mr(7)                            # v7 = ISO index
    sb_new(2); sb_s(2, 1, 'motion exp='); a.inv(0x6e, sbj, [2, 8, 9]); sb_s(2, 1, ' iso='); a.inv(0x6e, sbI, [2, 4])
    sb_s(2, 1, ' ss#='); a.inv(0x6e, sbI, [2, 3]); sb_s(2, 1, ' iso#='); a.inv(0x6e, sbI, [2, 7])
    a.raw(0x81 | 10 << 8 | 4 << 12); a.raw(0xbd | 8 << 8 | 10 << 12)                           # v8:v9 = total = exp * ISO
    a.b21(0x39, 3, 'mss'); a.b21(0x39, 7, 'miso')
    # both auto: Motion cap (exposure <= MOTEXP, ISO <= MOTISO)
    a.raw(0x81 | 10 << 8 | 4 << 12); a.raw(0x17 | 6 << 8, MOTEXP & 0xffff, MOTEXP >> 16)       # v10 = ISO; v6:v7 = cap
    a.raw(0xbd | 10 << 8 | 6 << 12)                                                               # v10 = ISO * cap
    a.raw(0x31 | 1 << 8, 8 | 10 << 8); a.b21(0x3d, 1, 'motok')                                  # total <= ISO*cap: as is
    a.raw(0x17 | 10 << 8, MOTEXP & 0xffff, MOTEXP >> 16); a.raw(0x009e | 10 << 8, 8 | 10 << 8)  # v10 = total / cap
    a.raw(0x84 | 4 << 8 | 10 << 12); a.raw(0x17 | 10 << 8, MOTEXP & 0xffff, MOTEXP >> 16)      # ISO; exposure = cap
    a.c16(1, MOTISO); a.b22(0x37, 4, 1, 'mset')
    a.raw(0x01 | 4 << 8 | 1 << 12); a.raw(0x81 | 10 << 8 | 1 << 12); a.raw(0x009e | 10 << 8, 8 | 10 << 8)
    a.go('mset')
    a.L('mss')                                                                                    # shutter fixed
    a.c16(1, 14); a.b22(0x33, 3, 1, 'mss2')                                                      # index 14: 3 s
    a.raw(0x17 | 10 << 8, 1500000000 & 0xffff, 1500000000 >> 16); a.c4(1, 1); a.go('mss3')
    a.L('mss2')
    a.raw(0x17 | 10 << 8, 500000 & 0xffff, 500000 >> 16); a.raw(0xd8 | 1 << 8, 3 | 0xff << 8)   # v1 = index - 1
    a.L('mss3')
    a.raw(0xc3 | 10 << 8 | 1 << 12)                                                               # shl-long/2addr v10, v1
    a.b21(0x39, 7, 'mboth')
    a.raw(0x009e | 6 << 8, 8 | 10 << 8); a.raw(0x84 | 4 << 8 | 6 << 12)                         # ISO = total / exposure
    a.c16(1, 50); a.b22(0x35, 4, 1, 'mc1'); a.raw(0x01 | 4 << 8 | 1 << 12)
    a.L('mc1'); a.c16(1, 6400); a.b22(0x37, 4, 1, 'mset'); a.raw(0x01 | 4 << 8 | 1 << 12); a.go('mset')
    a.L('mboth')                                                                                  # both fixed
    a.c16(4, 50); a.raw(0xd8 | 1 << 8, 7 | 0xff << 8); a.raw(0xb8 | 4 << 8 | 1 << 12); a.go('mset')
    a.L('miso')                                                                                   # ISO fixed, shutter auto
    a.c16(4, 50); a.raw(0xd8 | 1 << 8, 7 | 0xff << 8); a.raw(0xb8 | 4 << 8 | 1 << 12)
    a.raw(0x81 | 10 << 8 | 4 << 12); a.raw(0x009e | 10 << 8, 8 | 10 << 8)                       # exposure = total / ISO
    a.raw(0x17 | 6 << 8, 250000000 & 0xffff, 250000000 >> 16); a.raw(0x31 | 1 << 8, 10 | 6 << 8)
    a.b21(0x3d, 1, 'mc2'); a.raw(0x04 | 10 << 8 | 6 << 12)                                       # <= 1/4 s
    a.L('mc2'); a.raw(0x17 | 6 << 8, 100000 & 0xffff, 100000 >> 16); a.raw(0x31 | 1 << 8, 10 | 6 << 8)
    a.b21(0x3b, 1, 'mset'); a.raw(0x04 | 10 << 8 | 6 << 12)                                       # >= 0.1 ms
    a.L('mset')
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_EXPOSURE_TIME', RKEY))
    a.inv(0x71, g.M(LNG, 'valueOf', '(J)' + LNG), [10, 11]); a.mro(3)
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 3])
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_FRAME_DURATION', RKEY))                      # frame time >= exposure (HAL raises it)
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 3])
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_SENSITIVITY', RKEY))
    a.inv(0x71, ivo, [4]); a.mro(3)
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 3])
    a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'CONTROL_AE_MODE', RKEY))
    a.c4(3, 0); a.inv(0x71, ivo, [3]); a.mro(3)
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 3])
    sb_s(2, 3, ' -> exp='); a.inv(0x6e, sbj, [2, 10, 11]); sb_s(2, 3, ' iso='); a.inv(0x6e, sbI, [2, 4]); log_sb(2)
    a.go('motx')
    a.L('motna'); sb_new(2); sb_s(2, 3, 'motion: no manual exposure in request'); log_sb(2); a.go('motx')
    a.L('motok'); sb_s(2, 3, ' -> as is (already short)'); log_sb(2)
    a.L('motx'); a.c16(6, MOTQ); a.c4(7, 0); a.go('mot0')
    # ---- Long (Motion off, 50 MP quad shots only): GCam's short HDR+ frames -> longer exposure / lower ISO, same
    #      exposure x ISO: exposure up to LONGEXP ns, ISO not below LONGISO (RawR-like 1/15 s frames, less noise) ----
    NIGHTG = int(__import__('os').environ.get('NIGHTG256', '0'))   # P261: GCam may brighten <= NIGHTG256/256 x (724 = 1.5 EV)
    def night(lb):
        # v8:v9 planned exposure x ISO, v10:v11 our exposure, v4 our ISO, v5 props, v2 open log line; v1 v3 v6:v7 free
        if NIGHTG <= 0: return
        a.raw(0x81 | 6 << 8 | 4 << 12); a.raw(0xbd | 6 << 8 | 10 << 12)                       # v6:v7 = exposure x ISO
        a.raw(0x85 | 1 << 8 | 8 << 12); a.raw(0x85 | 3 << 8 | 6 << 12)                       # v1 = planned, v3 = actual (float)
        a.raw(0xc9 | 3 << 8 | 1 << 12)                                                         # v3 = actual / planned
        fb = struct.unpack('<I', struct.pack('<f', float(NIGHTG)))[0]
        a.raw(0x14 | 1 << 8, fb & 0xffff, fb >> 16); a.raw(0xc8 | 3 << 8 | 1 << 12)           # v3 *= NIGHTG256
        a.raw(0x87 | 3 << 8 | 3 << 12)                                                         # float-to-int
        a.c16(1, 256); a.b22(0x37, 3, 1, lb + 'a'); a.raw(0x01 | 3 << 8 | 1 << 12)           # <= 256
        a.L(lb + 'a'); a.c16(1, 32); a.b22(0x35, 3, 1, lb + 'b'); a.raw(0x01 | 3 << 8 | 1 << 12)   # >= 32
        a.L(lb + 'b')
        sb_s(2, 1, ' night='); a.inv(0x6e, sbI, [2, 3])
        a.inv(0x71, ivo, [3]); a.mro(3); a.cs(1, S('nightS')); a.inv(0x72, mput, [5, 1, 3])
    TELECAP = int(__import__('os').environ.get('TELECAP', '800'))    # P264: ISO cap for tele / teleconverter ('quadTo' = 5)
    def capload(lb):
        # v1 = ISO cap for this camera; v5 props; v3 temp
        a.cs(1, QKEY); a.inv(0x72, mget, [5, 1]); a.mro(3)
        a.cs(1, S('5')); a.inv(0x6e, g.M(STR, 'equals', '(' + OBJ + ')Z'), [1, 3]); a.mr(1); a.b21(0x38, 1, lb + 'm')
        a.c16(1, TELECAP); a.go(lb + 'd')
        a.L(lb + 'm'); a.c16(1, ISOCAP)
        a.L(lb + 'd')
    a.L('lng')
    LONGEXP = int(__import__('os').environ.get('LONGEXP', '30000000')); LONGISO = int(__import__('os').environ.get('LONGISO', '100'))
    if LONGEXP > 0:
        a.cs(1, QKEY); a.inv(0x72, mget, [5, 1]); a.mro(2); a.b21(0x38, 2, 'mot0')
        a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_EXPOSURE_TIME', RKEY))
        a.inv(0x6e, g.M(BLD, 'get', '(' + RKEY + ')' + OBJ), [12, 1]); a.mro(2)
        a.iof(3, 2, g.T(LNG)); a.b21(0x38, 3, 'mot0')
        a.t21(0x1f, 2, g.T(LNG)); a.inv(0x6e, g.M(LNG, 'longValue', '()J'), [2]); a.mrw(8)
        a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'SENSOR_SENSITIVITY', RKEY))
        a.inv(0x6e, g.M(BLD, 'get', '(' + RKEY + ')' + OBJ), [12, 1]); a.mro(2)
        a.iof(3, 2, tINT); a.b21(0x38, 3, 'mot0')
        a.t21(0x1f, 2, tINT); a.inv(0x6e, ivl, [2]); a.mr(4)
        a.raw(0x17 | 6 << 8, LONGEXP & 0xffff, LONGEXP >> 16)
        a.cs(1, S('TBlong')); a.inv(0x72, mget, [5, 1]); a.mro(2); a.iof(3, 2, g.T(LNG)); a.b21(0x38, 3, 'tbl0')   # P277
        a.t21(0x1f, 2, g.T(LNG)); a.inv(0x6e, g.M(LNG, 'longValue', '()J'), [2]); a.mrw(6)
        a.L('tbl0')
        # P286 (idea: Ray): handheld -> frames 1/50 s while the ISO stays <= HHISO; above that the frame gets longer
        #      (total / HHISO), never past LONGEXP. v6:v7 = cap; v10:v11, v2:v3, v1 temps
        HHE = int(__import__('os').environ.get('HHEXP', '20000000')); HHI = int(__import__('os').environ.get('HHISO', '400'))
        if HHE > 0:
            a.cs(1, S('TBhh')); a.inv(0x72, mget, [5, 1]); a.mro(2); a.b21(0x38, 2, 'hh0')
            a.raw(0x81 | 10 << 8 | 4 << 12); a.raw(0xbd | 10 << 8 | 8 << 12)                   # v10:v11 = exposure x ISO
            a.raw(0x17 | 2 << 8, HHI & 0xffff, HHI >> 16); a.raw(0xbe | 10 << 8 | 2 << 12)    # / HHISO
            a.raw(0x17 | 2 << 8, HHE & 0xffff, HHE >> 16); a.raw(0x31 | 1 << 8, 10 | 2 << 8)
            a.b21(0x3b, 1, 'hh1'); a.raw(0x04 | 10 << 8 | 2 << 12)                            # >= 1/50 s
            a.L('hh1'); a.raw(0x17 | 2 << 8, LONGEXP & 0xffff, LONGEXP >> 16); a.raw(0x31 | 1 << 8, 10 | 2 << 8)
            a.b21(0x3d, 1, 'hh2'); a.raw(0x04 | 10 << 8 | 2 << 12)                            # <= LONGEXP
            a.L('hh2'); a.raw(0x04 | 6 << 8 | 10 << 12)
            a.raw(0x31 | 1 << 8, 8 | 6 << 8); a.b21(0x3d, 1, 'hh3')                            # GCam's frame longer than that
            a.raw(0x31 | 1 << 8, 8 | 2 << 8); a.b21(0x3c, 1, 'hh3')                            # but <= LONGEXP: keep it as is
            a.raw(0x04 | 6 << 8 | 8 << 12)
            a.L('hh3')
            sb_new(2); sb_s(2, 3, 'handheld maxexp='); a.inv(0x6e, sbj, [2, 6, 7]); log_sb(2)
            a.L('hh0')
        DARK = int(__import__('os').environ.get('DARK256', '256'))     # frame gain x DARK/256 (181 = -0.5 EV, 128 = -1 EV), all 50 MP shots
        nolong = 'ldk' if DARK != 256 else 'lng0'
        CAPEXP = __import__('os').environ.get('CAPEXP', '1') == '1'; MAXISO = int(__import__('os').environ.get('MAXISO', '6400')); ISOCAP = int(__import__('os').environ.get('ISOCAP', '1600'))
        a.raw(0x31 | 1 << 8, 8 | 6 << 8)
        if CAPEXP: a.b21(0x3c, 1, 'lcap')                                                          # exposure > LONGEXP: cap
        a.b21(0x3b, 1, nolong)                                                                     # exposure == LONGEXP
        a.c16(1, LONGISO); a.b22(0x37, 4, 1, nolong)                                               # ISO <= LONGISO
        sb_new(2); sb_s(2, 3, 'long exp='); a.inv(0x6e, sbj, [2, 8, 9]); sb_s(2, 3, ' iso='); a.inv(0x6e, sbI, [2, 4])
        a.raw(0x81 | 10 << 8 | 4 << 12); a.raw(0xbd | 8 << 8 | 10 << 12)                       # v8:v9 = total
        a.raw(0x17 | 10 << 8, LONGISO & 0xffff, LONGISO >> 16); a.raw(0x9e | 10 << 8, 8 | 10 << 8)   # e2 = total / LONGISO
        a.raw(0x31 | 1 << 8, 10 | 6 << 8); a.b21(0x3d, 1, 'lk1'); a.raw(0x04 | 10 << 8 | 6 << 12)   # <= LONGEXP
        a.L('lk1')
        BAND = int(__import__('os').environ.get('BAND', '10000000'))    # P263: anti-banding step (50 Hz mains: 10 ms)
        if BAND > 0:
            a.raw(0x17 | 6 << 8, BAND & 0xffff, BAND >> 16); a.raw(0x31 | 1 << 8, 10 | 6 << 8); a.b21(0x3a, 1, 'bnd0')   # e2 < BAND: as is
            a.raw(0xbe | 10 << 8 | 6 << 12); a.raw(0xbd | 10 << 8 | 6 << 12)                   # e2 = floor(e2 / BAND) x BAND
            a.L('bnd0')
        a.raw(0x9e | 6 << 8, 8 | 10 << 8); a.raw(0x84 | 4 << 8 | 6 << 12)          # ISO = total / e2
        if DARK != 256:
            a.go('ldark')
            a.L('ldk'); a.raw(0x04 | 10 << 8 | 8 << 12)                                         # exposure unchanged
            sb_new(2); sb_s(2, 3, 'dark exp='); a.inv(0x6e, sbj, [2, 8, 9]); sb_s(2, 3, ' iso='); a.inv(0x6e, sbI, [2, 4])
            a.L('ldark')
            a.raw(0xd2 | 1 << 8 | 4 << 12, DARK); a.raw(0xd3 | 1 << 8 | 1 << 12, 256)          # v1 = ISO * DARK / 256
            a.c16(3, 50); a.b22(0x34, 1, 3, 'ldexp'); a.raw(0x01 | 4 << 8 | 1 << 12); a.go('mset')   # ISO >= 50: lower ISO
            a.L('ldexp')                                                                          # else shorten exposure
            a.raw(0x17 | 6 << 8, DARK, 0); a.raw(0xbd | 10 << 8 | 6 << 12)
            a.raw(0x17 | 6 << 8, 256, 0); a.raw(0xbe | 10 << 8 | 6 << 12); a.go('mset')
        a.c16(1, 50); a.b22(0x35, 4, 1, 'lk2'); a.raw(0x01 | 4 << 8 | 1 << 12)
        a.L('lk2')
        if ISOCAP > 0:                                                                            # RawR-like ISO ceiling: keep the exposure, underexpose
            capload('cp1'); a.b22(0x37, 4, 1, 'lic1'); a.raw(0x01 | 4 << 8 | 1 << 12)
            sb_s(2, 3, ' isocap')                                   # v2 is the open 'long/cap' log line (mset appends)
            night('ngt1')
            a.L('lic1')
        a.go('mset')
        if CAPEXP:
            # GCam asked for frames longer than LONGEXP (night): shorten to LONGEXP, raise ISO (max MAXISO), same total
            a.L('lcap')
            sb_new(2); sb_s(2, 3, 'cap exp='); a.inv(0x6e, sbj, [2, 8, 9]); sb_s(2, 3, ' iso='); a.inv(0x6e, sbI, [2, 4])
            NIGHTEXP = int(__import__('os').environ.get('NIGHTEXP', '60000000'))   # P262: night (GCam wants > LONGEXP): frames up to NIGHTEXP, OIS on
            if NIGHTEXP > LONGEXP:
                a.raw(0x17 | 6 << 8, NIGHTEXP & 0xffff, NIGHTEXP >> 16)                          # v6 = NIGHTEXP
                a.raw(0x31 | 1 << 8, 8 | 6 << 8); a.b21(0x3c, 1, 'nx2')                         # exposure > NIGHTEXP: v6 stays
                a.raw(0x04 | 6 << 8 | 8 << 12)                                                   # else v6 = exposure
                a.L('nx2')
                a.raw(0x62 | 1 << 8, g.Fd(CRQ, 'LENS_OPTICAL_STABILIZATION_MODE', RKEY))
                a.c4(3, 1); a.inv(0x71, ivo, [3]); a.mro(3); a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 3])
                sb_s(2, 3, ' night ois')
                a.cs(1, S('TBNOIS')); a.inv(0x72, mput, [5, 1, 1])                             # P265: longer settle
            a.raw(0x81 | 10 << 8 | 4 << 12); a.raw(0xbd | 8 << 8 | 10 << 12)                   # v8:v9 = total
            if NIGHTEXP > LONGEXP: a.raw(0x04 | 10 << 8 | 6 << 12)                              # e2 = night exposure
            else: a.raw(0x17 | 10 << 8, LONGEXP & 0xffff, LONGEXP >> 16)                         # e2 = LONGEXP
            a.raw(0x9e | 6 << 8, 8 | 10 << 8); a.raw(0x84 | 4 << 8 | 6 << 12)                  # ISO = total / e2
            if ISOCAP > 0:                                                                        # RawR-like ISO ceiling: keep 1/15 s, underexpose
                capload('cp2'); a.b22(0x37, 4, 1, 'lic2'); a.raw(0x01 | 4 << 8 | 1 << 12)
                sb_s(2, 3, ' isocap')                                   # v2 is the open 'long/cap' log line (mset appends)
                night('ngt2')
                a.L('lic2'); a.go('mset')
            else:
                a.c16(1, MAXISO); a.b22(0x37, 4, 1, 'lc1')                                         # ISO <= MAXISO: done
                a.raw(0x01 | 4 << 8 | 1 << 12); a.raw(0x17 | 6 << 8, MAXISO & 0xffff, MAXISO >> 16)
                a.raw(0x9e | 10 << 8, 8 | 6 << 8)                                                  # e2 = total / MAXISO
                a.L('lc1'); a.go('mset')
        a.L('lng0'); a.c16(6, int(__import__('os').environ.get('QISO', '32767'))); a.c4(7, 0)
    a.L('mot0')
    a.inv(0x71, getp, []); a.mro(5); a.cs(1, QKEY); a.inv(0x72, mget, [5, 1]); a.mro(0); a.b21(0x38, 0, 'null')
    # low light: vivo's own remosaic (smoothed) is cleaner than per-pixel quad -> quad only up to QISO (viewfinder ISO)
    a.cs(1, S('quadOn')); a.inv(0x72, mrem, [5, 1])
    # ---- Leica button = remosaic compare: on -> vivo's own remosaic (no quad) for this shot ----
    if __import__('os').environ.get('NO200', '1') == '1':
        a.cs(1, S('setTemporalBinning')); a.inv(0x71, g.M('LMC/pref;', 'MenuValue', '(' + STR + ')I'), [1]); a.mr(1)
        if REM3: a.c4(2, 2); a.b22(0x33, 1, 2, 'nostock')                   # if-ne v1, 2 (SR = 2)
        else: a.b21(0x38, 1, 'nostock')
        a.cs(1, S('SR')); a.inv(0x71, g.M('LTBDF;', 'tag', '(' + STR + ')V'), [1])                                # P280: file name tag
        sb_new(2); sb_s(2, 3, 'quad skip: SR stock remosaic' if REM3 else 'quad skip: stock remosaic (compare button)'); log_sb(2); a.go('null')
        a.L('nostock')
    # the ISO of this still request (GCam's shot AE, set on the builder before build()); viewfinder ISO if absent
    a.raw(0x62 | 1 << 8, g.Fd('Landroid/hardware/camera2/CaptureRequest;', 'SENSOR_SENSITIVITY', RKEY))
    a.inv(0x6e, g.M(BLD, 'get', '(' + RKEY + ')' + OBJ), [12, 1]); a.mro(2)
    a.iof(3, 2, tINT); a.b21(0x39, 3, 'qisoh')
    a.cs(1, S('ISOSpeedLatitudezzz')); a.inv(0x72, mget, [5, 1]); a.mro(2)
    a.L('qisoh')
    # mode: shot ISO <= QISO -> 0 (Detail remosaic, full 50 MP detail), above -> 1 (quad binning: 4-pixel means,
    # half the noise, 12.5 MP detail upsampled); QMODE forces one (2 or 3 = XR)
    if REM3:   # button: 0 XR -> mode 3 (own XR remosaic), 1 ER -> mode 0 (RawR Detail)
        a.cs(4, S('setTemporalBinning')); a.inv(0x71, g.M('LMC/pref;', 'MenuValue', '(' + STR + ')I'), [4]); a.mr(4)
        a.b21(0x39, 4, 'qer'); a.c4(4, 3); a.cs(1, S('XR')); a.go('qrm'); a.L('qer'); a.c4(4, 0); a.cs(1, S('ER')); a.L('qrm')
        a.inv(0x71, g.M('LTBDF;', 'tag', '(' + STR + ')V'), [1])                                                   # P280: file name tag
    else:
        a.c4(4, int(__import__('os').environ.get('QLOW', '3')))             # low ISO: 3 XR, 0 RawR Detail
    a.iof(3, 2, tINT); a.b21(0x38, 3, 'qiso')
    a.t21(0x1f, 2, tINT); a.inv(0x6e, ivl, [2]); a.mr(3)
    a.b22(0x37, 3, 6, 'qiso')                                              # if-le iso, QISO (MOTQISO in Motion)
    if __import__('os').environ.get('QHIGH', 'vivo') == 'vivo':
        # above QISO: no quad at all -> vivo's own (ISP-denoised) remosaic, as without this patch
        a.cs(1, S('SR')); a.inv(0x71, g.M('LTBDF;', 'tag', '(' + STR + ')V'), [1])
        sb_new(6); sb_s(6, 7, 'quad skip iso='); a.inv(0x6e, sbI, [6, 3]); log_sb(6); a.go('null')
    else:
        a.c4(4, 1)
    a.L('qiso')
    if __import__('os').environ.get('QMODE'): a.c4(4, int(__import__('os').environ['QMODE']))
    a.inv(0x71, ivo, [4]); a.mro(4)
    sb_new(6); sb_s(6, 7, 'quad still request iso='); a.inv(0x6e, sbo, [6, 2]); sb_s(6, 7, ' mode='); a.inv(0x6e, sbo, [6, 4]); log_sb(6)
    a.cs(1, S('quadOn')); a.inv(0x72, mput, [5, 1, 4])
    if PVW:
        # PVW: the burst frames also go to the viewfinder's surfaces (the preview request Llei last completed, stored by
        # build M1 under the CaptureRequest class key), so the preview keeps moving during the 50 MP burst
        CRQT = g.T('Landroid/hardware/camera2/CaptureRequest;'); MTH = 'Ljava/lang/reflect/Method;'; CLS = 'Ljava/lang/Class;'
        a.L('pv0')                                                    # v0 ('quadTo' id) stays untouched
        a.t21(0x1c, 1, CRQT); a.inv(0x72, mget, [5, 1]); a.mro(1); a.iof(2, 1, CRQT); a.b21(0x38, 2, 'pv1')
        a.t21(0x1c, 3, CRQT); a.cs(2, S('getTargets')); a.c4(6, 0); a.raw(0x23 | 6 << 8 | 6 << 12, g.T('[Ljava/lang/Class;'))
        a.inv(0x6e, g.M(CLS, 'getDeclaredMethod', '(' + STR + '[Ljava/lang/Class;)' + MTH), [3, 2, 6]); a.mro(2)
        a.c4(3, 1); a.inv(0x6e, g.M(MTH, 'setAccessible', '(Z)V'), [2, 3])
        a.c4(3, 0); a.raw(0x23 | 3 << 8 | 3 << 12, tOA)
        a.inv(0x6e, g.M(MTH, 'invoke', '(' + OBJ + '[Ljava/lang/Object;)' + OBJ), [2, 1, 3]); a.mro(2)
        a.t21(0x1f, 2, g.T('Ljava/util/Collection;'))
        a.inv(0x72, g.M('Ljava/util/Collection;', 'iterator', '()Ljava/util/Iterator;'), [2]); a.mro(2)
        sb_new(6); sb_s(6, 7, 'pvw')
        a.L('pvl')
        a.inv(0x72, g.M('Ljava/util/Iterator;', 'hasNext', '()Z'), [2]); a.mr(3); a.b21(0x38, 3, 'pvd')
        a.inv(0x72, g.M('Ljava/util/Iterator;', 'next', '()' + OBJ), [2]); a.mro(3)
        a.iof(7, 3, g.T('Landroid/view/Surface;')); a.b21(0x38, 7, 'pvl')
        a.t21(0x1f, 3, g.T('Landroid/view/Surface;'))
        a.inv(0x6e, g.M(BLD, 'addTarget', '(Landroid/view/Surface;)V'), [12, 3])
        sb_s(6, 7, ' +'); a.inv(0x6e, sbo, [6, 3]); a.go('pvl')
        a.L('pvd'); log_sb(6)
        a.L('pv1')
        SUBTRY.append(('pv0', 'pv1', 'pvx'))
    if __import__('os').environ.get('QREMREJ') == '1':     # quad still without GCam's 4080-wide reader
        a.cs(1, S('rejected')); a.inv(0x72, mget, [5, 1]); a.mro(0); a.b21(0x38, 0, 'qbrej')
        a.t21(0x1f, 0, g.T('Landroid/media/ImageReader;'))
        a.inv(0x6e, g.M('Landroid/media/ImageReader;', 'getSurface', '()Landroid/view/Surface;'), [0]); a.mro(0)
        a.inv(0x6e, g.M(BLD, 'removeTarget', '(Landroid/view/Surface;)V'), [12, 0])
        a.L('qbrej')
    a.t21(0x22, 1, g.T(RKEY)); a.cs(2, S('vivo.control.forceSensorMode')); a.t21(0x1c, 3, g.T('[I'))
    a.inv(0x70, g.M(RKEY, '<init>', '(' + STR + 'Ljava/lang/Class;)V'), [1, 2, 3])
    a.c4(2, 1); a.raw(0x23 | 3 << 8 | 2 << 12, g.T('[I'))
    # sensor mode: main (id 3) row 3, tele (id 5) row 1 (probe 2026-11-21: the native quad rows); v0 = 'quadTo' = id
    a.cs(2, S('5')); a.inv(0x6e, g.M(STR, 'equals', '(' + OBJ + ')Z'), [2, 0]); a.mr(2); a.b21(0x38, 2, 'qmuw')
    a.c4(2, 1); a.go('qmset')
    a.L('qmuw')
    a.cs(2, S('4')); a.inv(0x6e, g.M(STR, 'equals', '(' + OBJ + ')Z'), [2, 0]); a.mr(2); a.b21(0x38, 2, 'qm3')
    a.c4(2, int(__import__('os').environ.get('UWROW', '4'))); a.go('qmset')      # ultra-wide row (probe)
    a.L('qm3'); a.c4(2, 3)
    a.L('qmset'); a.c4(4, 0); a.raw(0x4b | 2 << 8, 3 | 4 << 8)   # int[]{row}
    a.inv(0x6e, g.M(BLD, 'set', '(' + RKEY + OBJ + ')V'), [12, 1, 3])
    a.go('null')
    a.L('qb0')
    SETTLE = int(__import__('os').environ.get('SETTLE', '300'))
    if SETTLE > 0:
        # ---- P239 settle (CameraCaptureSession, from Llei.onCaptureSequenceCompleted before the viewfinder restart):
        #      after the LAST 50 MP burst frame (props 'TBREM', set when the paced burst starts) run the viewfinder
        #      request for SETTLE ms WITHOUT its display surface(s), so the ~250 ms offset the HAL/OIS shows right
        #      after the switch back from the full-resolution mode never reaches the screen (frozen frame stays).
        #      Any failure -> the normal restart that follows. ----
        DEV = 'Landroid/hardware/camera2/CameraDevice;'; SURF = 'Landroid/view/Surface;'; CLS = 'Ljava/lang/Class;'
        MTH = 'Ljava/lang/reflect/Method;'; ITR = 'Ljava/util/Iterator;'; COL = 'Ljava/util/Collection;'
        BLDs = 'Landroid/hardware/camera2/CaptureRequest$Builder;'; RKEYs = 'Landroid/hardware/camera2/CaptureRequest$Key;'
        gdm2 = g.M(CLS, 'getDeclaredMethod', '(' + STR + '[' + CLS + ')' + MTH)
        sacc = g.M(MTH, 'setAccessible', '(Z)V'); minv2 = g.M(MTH, 'invoke', '(' + OBJ + '[' + OBJ + ')' + OBJ)
        hasn = g.M(ITR, 'hasNext', '()Z'); nxt = g.M(ITR, 'next', '()' + OBJ)
        a.iof(0, 12, tSES); a.b21(0x38, 0, 'ss0')
        a.t21(0x1f, 12, tSES)
        a.inv(0x71, getp, []); a.mro(1)
        a.cs(2, S('TBREM')); a.inv(0x72, mget, [1, 2]); a.mro(3)
        a.iof(0, 3, tINT); a.b21(0x38, 0, 'null')
        a.t21(0x1f, 3, tINT); a.inv(0x6e, ivl, [3]); a.mr(3)
        a.raw(0xd8 | 3 << 8, 3 | 0xff << 8)                                    # add-int/lit8 v3, v3, -1
        a.b21(0x3d, 3, 'ssgo')                                                 # last frame -> settle
        a.inv(0x71, ivo, [3]); a.mro(0); a.inv(0x72, mput, [1, 2, 0]); a.go('null')
        a.L('ssgo')
        a.inv(0x71, g.M('LTBProg;', 'en', '()V'), [])                                     # P281: ring done
        a.inv(0x72, mrem, [1, 2])
        a.cs(2, S('RAW50_REPEAT')); a.inv(0x72, mget, [1, 2]); a.mro(4)
        a.iof(0, 4, tREQ); a.b21(0x38, 0, 'null'); a.t21(0x1f, 4, tREQ)
        a.inv(0x6e, g.M(SES, 'getDevice', '()' + DEV), [12]); a.mro(5)
        a.c4(0, 1); a.inv(0x6e, g.M(DEV, 'createCaptureRequest', '(I)' + BLDs), [5, 0]); a.mro(5)   # TEMPLATE_PREVIEW
        # copy every key of the viewfinder request
        a.inv(0x6e, g.M(REQ, 'getKeys', '()Ljava/util/List;'), [4]); a.mro(6)
        a.inv(0x72, g.M('Ljava/util/List;', 'iterator', '()' + ITR), [6]); a.mro(6)
        a.L('ssk')
        a.inv(0x72, hasn, [6]); a.mr(0); a.b21(0x38, 0, 'sskd')
        a.inv(0x72, nxt, [6]); a.mro(7); a.t21(0x1f, 7, g.T(RKEYs))
        a.inv(0x6e, g.M(REQ, 'get', '(' + RKEYs + ')' + OBJ), [4, 7]); a.mro(8)
        a.inv(0x6e, g.M(BLDs, 'set', '(' + RKEYs + OBJ + ')V'), [5, 7, 8]); a.go('ssk')
        a.L('sskd')
        # P241: same tag as the viewfinder request (GCam's callbacks map every request by its tag: Ldh.b(tag.getClass())
        # -> NPE in Llei.onCaptureProgressed for P240's untagged settle request, LMC crash log 2026-11-24 00:27)
        a.inv(0x6e, g.M(REQ, 'getTag', '()' + OBJ), [4]); a.mro(8)
        a.inv(0x6e, g.M(BLDs, 'setTag', '(' + OBJ + ')V'), [5, 8])
        # P240: the only non-display target used is GCam's 12 MP RAW ZSL reader (props 'rejected', 4080/4096 wide,
        # stored by Lkyu), if the viewfinder request targets it. (P239 asked the hidden SurfaceUtils.isSurfaceForPreview,
        # which Android 17 no longer has: NoSuchMethodException.)
        a.cs(2, S('rejected')); a.inv(0x72, mget, [1, 2]); a.mro(7)
        a.iof(0, 7, g.T('Landroid/media/ImageReader;')); a.b21(0x38, 0, 'ssnone')
        a.t21(0x1f, 7, g.T('Landroid/media/ImageReader;'))
        a.inv(0x6e, g.M('Landroid/media/ImageReader;', 'getSurface', '()' + SURF), [7]); a.mro(7)
        # targets of the viewfinder request (hidden CaptureRequest.getTargets(), as PVW)
        a.t21(0x1c, 0, tREQ); a.cs(2, S('getTargets'))
        a.c4(8, 0); a.raw(0x23 | 10 << 8 | 8 << 12, g.T('[' + CLS))
        a.inv(0x6e, gdm2, [0, 2, 10]); a.mro(0); a.c4(8, 1); a.inv(0x6e, sacc, [0, 8])
        a.c4(8, 0); a.raw(0x23 | 10 << 8 | 8 << 12, tOA)
        a.inv(0x6e, minv2, [0, 4, 10]); a.mro(6); a.t21(0x1f, 6, g.T(COL))
        a.c4(9, 0)
        a.inv(0x72, g.M(COL, 'contains', '(' + OBJ + ')Z'), [6, 7]); a.mr(0); a.b21(0x38, 0, 'sstd')
        a.inv(0x6e, g.M(BLDs, 'addTarget', '(' + SURF + ')V'), [5, 7]); a.c4(9, 1)
        a.L('sstd')
        a.b21(0x38, 9, 'ssnone')
        a.cs(2, S('RAW50_C_PROBE1')); a.inv(0x72, mget, [1, 2]); a.mro(7)
        a.iof(0, 7, tCB); a.b21(0x39, 0, 'sscb'); a.c4(7, 0); a.go('sscb2')
        a.L('sscb'); a.t21(0x1f, 7, tCB)
        a.L('sscb2')
        a.inv(0x71, mainl, []); a.mro(8); a.t21(0x22, 11, tHND)
        a.inv(0x70, g.M(HND, '<init>', '(Landroid/os/Looper;)V'), [11, 8])
        a.inv(0x6e, g.M(BLDs, 'build', '()' + REQ), [5]); a.mro(5)
        a.inv(0x6e, g.M(SES, 'setRepeatingRequest', '(' + REQ + CB + HND + ')I'), [12, 5, 7, 11]); a.mr(0)
        SETTLEN = int(__import__('os').environ.get('SETTLEN', '1500'))   # P265: night burst with OIS on -> longer hold (OIS re-centres slowly)
        a.cs(2, S('TBNOIS')); a.inv(0x72, mrem, [1, 2]); a.mro(0); a.b21(0x38, 0, 'sst0')
        a.raw(0x16 | 2 << 8, SETTLEN); a.go('sst1')
        a.L('sst0'); a.raw(0x16 | 2 << 8, SETTLE)                             # const-wide/16 v2, SETTLE
        a.L('sst1')
        a.inv(0x71, g.M('Ljava/lang/Thread;', 'sleep', '(J)V'), [2, 3])
        sb_new(6); sb_s(6, 7, 'settle ms='); a.inv(0x6e, sbj, [6, 2, 3]); sb_s(6, 7, ', viewfinder held, targets='); a.inv(0x6e, sbI, [6, 9]); log_sb(6)
        a.go('null')
        a.L('ssnone'); sb_new(6); sb_s(6, 7, 'settle skipped: ZSL reader not a viewfinder target'); log_sb(6); a.go('null')
        a.L('ss0')
    # P247: Ldxh (Ldvm.o entry = one HDR+ payload frame about to be fed): register every raw 50 MP frame held in the
    # props slots (Image, RAW_SENSOR, 8192 wide) with libtbin (N.p) so the first frame's conversion can pre-merge them
    if int(__import__('os').environ.get('MRG', '1')):
        _ITR = 'Ljava/util/Iterator;'; _COL = 'Ljava/util/Collection;'
        a.iof(0, 12, g.T('Ldxh;')); a.b21(0x38, 0, 'pm0')
        a.c4(4, 0)
        a.inv(0x71, getp, []); a.mro(1)
        a.inv(0x6e, g.M('Ljava/util/Hashtable;', 'values', '()' + _COL), [1]); a.mro(1)
        a.inv(0x72, g.M(_COL, 'iterator', '()' + _ITR), [1]); a.mro(1)
        a.L('pml')
        a.inv(0x72, g.M(_ITR, 'hasNext', '()Z'), [1]); a.mr(0); a.b21(0x38, 0, 'pmd')
        a.inv(0x72, g.M(_ITR, 'next', '()' + OBJ), [1]); a.mro(2)
        a.iof(0, 2, tIMG); a.b21(0x38, 0, 'pml'); a.t21(0x1f, 2, tIMG)
        a.inv(0x6e, g.M(IMG, 'getFormat', '()I'), [2]); a.mr(0); a.c16(3, 0x20); a.b22(0x33, 0, 3, 'pml')
        a.inv(0x6e, gw, [2]); a.mr(0); a.c16(3, 8192); a.b22(0x33, 0, 3, 'pml')
        a.inv(0x6e, gp, [2]); a.mro(2); a.c4(3, 0); a.raw(0x46 | 2 << 8, 2 | 3 << 8)      # aget-object v2, v2, v3
        a.inv(0x6e, grs, [2]); a.mr(3); a.inv(0x6e, gbuf, [2]); a.mro(2)
        a.inv(0x71, g.M(NCL, 'p', '(' + BB + 'I)I'), [2, 3]); a.mr(4); a.go('pml')
        a.L('pmd')
        sb_new(6); sb_s(6, 7, 'premerge reg '); a.inv(0x6e, sbI, [6, 4]); log_sb(6)
        a.go('null')
        a.L('pm0')
    # Lnns (Llet.close): give a pool buffer back
    a.iof(0, 12, g.T('Lnns;')); a.b21(0x38, 0, 'qr0')
    a.t21(0x1f, 12, g.T('Ljava/util/List;'))
    a.inv(0x72, g.M('Ljava/util/List;', 'size', '()I'), [12]); a.mr(0); a.b21(0x3d, 0, 'null')
    a.c4(0, 0); a.inv(0x72, g.M('Ljava/util/List;', 'get', '(I)' + OBJ), [12, 0]); a.mro(0)
    a.iof(1, 0, g.T('Lles;')); a.b21(0x38, 1, 'null'); a.t21(0x1f, 0, g.T('Lles;'))
    a.inv(0x6e, g.M('Lles;', 'getBuffer', '()' + BB), [0]); a.mro(0)        # Lles.c is private
    a.inv(0x71, nr, [0]); a.go('null')
    a.L('qr0')
    # Image 8192 wide from Llet.<init> off the main thread (Ldvm.E: an HDR+ payload frame) with 'quadTo' set:
    # quad -> Bayer into a pool buffer, returns the plane list for Llet.g
    a.go('ql0')
    a.L('quadimg')
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, S('quadOn')); a.inv(0x72, mget, [0, 1]); a.mro(0); a.b21(0x38, 0, 'null')
    a.c4(10, 0); a.iof(1, 0, tINT); a.b21(0x38, 1, 'qmd')
    a.t21(0x1f, 0, tINT); a.inv(0x6e, ivl, [0]); a.mr(10); a.raw(0xe0 | 10 << 8, 10 | 16 << 8)   # v10 = mode << 16
    a.L('qmd')
    DNC = int(__import__('os').environ.get('DNC', '0')) & 7; DNL = int(__import__('os').environ.get('DNL', '0')) & 7
    if DNC or DNL:     # light denoise after the remosaic: bits 23-25 chroma (x0.1), 26-28 luma (x0.05)
        a.raw(0x15 | 1 << 8, (DNC << 7 | DNL << 10)); a.raw(0xb6 | 10 << 8 | 1 << 12)   # const/high16 v1; or-int/2addr v10, v1
    a.inv(0x6e, gp, [12]); a.mro(0); a.c4(1, 0); a.raw(0x0046, 0x0100)
    a.inv(0x6e, grs, [0]); a.mr(1); a.inv(0x6e, gbuf, [0]); a.mro(0)
    a.inv(0x71, na_, []); a.mro(4); a.b21(0x39, 4, 'qhave')
    sb_new(6); sb_s(6, 7, 'quad pool full'); log_sb(6); a.go('null')
    a.L('qhave')
    a.inv(0x71, nano, []); a.mrw(8)
    a.c16(2, 8160); a.raw(0xb6 | 2 << 8 | 10 << 12); a.c16(3, 6128)               # or-int/2addr v2, v10 (mode)
    a.inv(0x71, getp, []); a.mro(6); a.cs(7, QKEY); a.inv(0x72, mget, [6, 7]); a.mro(6)
    a.cs(7, S('5')); a.inv(0x6e, g.M(STR, 'equals', '(' + OBJ + ')Z'), [7, 6]); a.mr(7); a.b21(0x38, 7, 'qhuw')
    a.c16(3, 6144); a.go('qhmain')                                          # tele: 8160 x 6144
    a.L('qhuw')
    a.cs(7, S('4')); a.inv(0x6e, g.M(STR, 'equals', '(' + OBJ + ')Z'), [7, 6]); a.mr(7); a.b21(0x38, 7, 'qhmain')
    a.c16(3, 6144); a.c16(2, 8192); a.raw(0xb6 | 2 << 8 | 10 << 12)        # ultra-wide: 8192 x 6144 (| mode)
    if __import__('os').environ.get('NOQSC') != '1':
        # UW quad sensitivity correction: bit 18 + focus weight k (0 infinity .. 15 at >= 2.48 dpt) in bits 19-22,
        # from the last viewfinder LENS_FOCUS_DISTANCE (props 'CdrSCFocus', stored by M1)
        a.inv(0x71, getp, []); a.mro(6); a.cs(7, S('CdrSCFocus')); a.inv(0x72, mget, [6, 7]); a.mro(6)
        a.iof(7, 6, g.T('Ljava/lang/Float;')); a.b21(0x38, 7, 'qfk0')
        a.t21(0x1f, 6, g.T('Ljava/lang/Float;'))
        a.inv(0x6e, g.M('Ljava/lang/Float;', 'floatValue', '()F'), [6]); a.mr(6)
        import struct as _st
        k = _st.unpack('<I', _st.pack('<f', 15.0 / 2.48))[0]
        a.raw(0x14 | 7 << 8, k & 0xffff, k >> 16); a.raw(0xc8 | 6 << 8 | 7 << 12)      # mul-float/2addr v6, v7
        k = _st.unpack('<I', _st.pack('<f', 0.5))[0]
        a.raw(0x14 | 7 << 8, k & 0xffff, k >> 16); a.raw(0xc6 | 6 << 8 | 7 << 12)      # add-float/2addr v6, v7
        a.raw(0x87 | 6 << 8 | 6 << 12)                                                   # float-to-int v6, v6
        a.b21(0x3b, 6, 'qfpos'); a.c4(6, 0)                                             # if-gez
        a.L('qfpos'); a.c16(7, 15); a.b22(0x37, 6, 7, 'qfk'); a.c16(6, 15)              # if-le k, 15
        a.go('qfk')
        a.L('qfk0'); a.c4(6, 0)
        a.L('qfk')
        a.raw(0xe0 | 6 << 8, 6 | 3 << 8); a.raw(0xde | 6 << 8, 6 | 4 << 8)             # k << 3 | 4 (QSC on)
        a.raw(0xe0 | 6 << 8, 6 | 16 << 8); a.raw(0xb6 | 2 << 8 | 6 << 12)              # << 16, or into v2
    a.L('qhmain')
    a.inv(0x71, nq, [0, 1, 2, 3, 4]); a.mr(5)
    a.c4(12, -1)                                                            # t = -1 in the log: quad
    a.b21(0x38, 5, 'workers')
    a.inv(0x71, nr, [4]); a.go('pfail')
    a.L('ql0')
    # ---- MeteringRectangle[] (CONTROL_AF_REGIONS of a request): empty "camera decides" region -> centre of the
    #      viewfinder crop (props 'Landroid/graphics/Rect;' from Llei), 1/4 x 1/4, weight 1000; else null (unchanged) ----
    MR = 'Landroid/hardware/camera2/params/MeteringRectangle;'; tMRA = g.T('[' + MR); RECT = 'Landroid/graphics/Rect;'
    a.iof(0, 12, tMRA); a.b21(0x38, 0, 'mr0')
    a.t21(0x1f, 12, tMRA)
    a.raw(0x21 | 0 << 8 | 12 << 12); a.c4(1, 1); a.b22(0x32, 0, 1, 'mrok'); a.go('null')     # length must be 1
    a.L('mrok')
    a.c4(1, 0); a.raw(0x46 | 2 << 8, 12 | 1 << 8)                     # v2 = arr[0]
    a.inv(0x6e, g.M(MR, 'getMeteringWeight', '()I'), [2]); a.mr(0); a.b21(0x39, 0, 'null')
    a.inv(0x6e, g.M(MR, 'getWidth', '()I'), [2]); a.mr(0); a.b21(0x39, 0, 'null')
    a.inv(0x71, getp, []); a.mro(1); a.cs(2, S(RECT)); a.inv(0x72, mget, [1, 2]); a.mro(3); a.b21(0x38, 3, 'null')
    a.t21(0x1f, 3, g.T(RECT))
    # same crop as last time -> the same array object (request key/values compare equal, no request churn)
    a.cs(2, S('TBAFC')); a.inv(0x72, mget, [1, 2]); a.mro(4)
    a.inv(0x6e, g.M(RECT, 'equals', '(' + OBJ + ')Z'), [3, 4]); a.mr(0); a.b21(0x38, 0, 'mrnew')
    a.cs(2, S('TBAFR')); a.inv(0x72, mget, [1, 2]); a.mro(0); a.b21(0x38, 0, 'mrnew'); a.raw(0x11 | 0 << 8)
    a.L('mrnew')
    a.inv(0x6e, g.M(RECT, 'width', '()I'), [3]); a.mr(4); a.raw(0xdb | 4 << 8, 4 | 4 << 8)      # div-int/lit8 v4, v4, 4
    a.inv(0x6e, g.M(RECT, 'height', '()I'), [3]); a.mr(5); a.raw(0xdb | 5 << 8, 5 | 4 << 8)
    a.b21(0x3d, 4, 'null'); a.b21(0x3d, 5, 'null')
    a.inv(0x6e, g.M(RECT, 'centerX', '()I'), [3]); a.mr(7); a.inv(0x6e, g.M(RECT, 'centerY', '()I'), [3]); a.mr(8)
    a.raw(0xdb | 0 << 8, 4 | 2 << 8); a.raw(0xb1 | 7 << 8 | 0 << 12)  # left = cx - w/2
    a.raw(0xdb | 0 << 8, 5 | 2 << 8); a.raw(0xb1 | 8 << 8 | 0 << 12)  # top  = cy - h/2
    a.raw(0x01 | 9 << 8 | 4 << 12); a.raw(0x01 | 10 << 8 | 5 << 12)    # move v9 = w, v10 = h
    a.raw(0x13 | 11 << 8, 1000)                                       # weight
    a.t21(0x22, 6, g.T(MR)); a.raw(0x76 | 6 << 8, g.M(MR, '<init>', '(IIIII)V'), 6)   # invoke-direct/range {v6..v11}
    a.c4(0, 1); a.raw(0x23 | 1 << 8 | 0 << 12, tMRA)                  # v1 = new MR[1]
    a.c4(0, 0); a.raw(0x4d | 6 << 8, 1 | 0 << 8)                      # v1[0] = v6
    a.inv(0x71, getp, []); a.mro(9)
    a.cs(2, S('TBAFC')); a.inv(0x72, mput, [9, 2, 3]); a.cs(2, S('TBAFR')); a.inv(0x72, mput, [9, 2, 1])
    sb_new(6); sb_s(6, 7, 'AFR centre '); a.raw(0x07 | 0 << 8 | 1 << 12)
    a.inv(0x71, g.M('Ljava/util/Arrays;', 'toString', '([Ljava/lang/Object;)' + STR), [1]); a.mro(1)
    a.inv(0x6e, sbs, [6, 1]); log_sb(6)
    a.raw(0x11 | 0 << 8)                                              # return the array
    a.L('mr0')
    # ---- Object[5] {session, request, callback, handler, Integer n}: 200 MP -> queue n-1 one-by-one captures ----
    a.iof(0, 12, tOA); a.b21(0x38, 0, 'st')
    a.t21(0x1f, 12, tOA)
    # Object[3] {session, request, callback} from Llei.onCaptureFailed (RES burst): resend the failed frame once, so
    # the HDR+ shot gets its full frame count instead of waiting ~10 s for it (and the postview with it)
    a.raw(0x21 | 0 << 8 | 12 << 12); a.c4(1, 3); a.b22(0x33, 0, 1, 'rt0')
    # at most 6 resends per shot (counter 'TBRTN', reset by every burst request build); the burst reuses one request
    a.inv(0x71, getp, []); a.mro(1); a.cs(2, S('TBRTN')); a.inv(0x72, mget, [1, 2]); a.mro(3)
    a.c4(0, 0); a.iof(4, 3, tINT); a.b21(0x38, 4, 'rtn')
    a.t21(0x1f, 3, tINT); a.inv(0x6e, ivl, [3]); a.mr(0)
    a.L('rtn')
    a.c4(4, 6); a.b22(0x34, 0, 4, 'rtok')                                   # if-lt n, 6
    sb_new(6); sb_s(6, 7, 'retry limit reached'); log_sb(6); a.go('null')
    a.L('rtok')
    a.raw(0xd8 | 0 << 8, 0 | 1 << 8); a.inv(0x71, ivo, [0]); a.mro(3); a.inv(0x72, mput, [1, 2, 3])
    a.c4(0, 1); a.raw(0x46 | 4 << 8, 12 | 0 << 8)                          # v4 = request
    a.L('rtgo')
    a.c4(0, 0); a.raw(0x46 | 5 << 8, 12 | 0 << 8); a.t21(0x1f, 5, tSES)
    a.c4(0, 2); a.raw(0x46 | 6 << 8, 12 | 0 << 8); a.t21(0x1f, 6, tCB)
    a.t21(0x1f, 4, tREQ)
    a.inv(0x71, mainl, []); a.mro(8); a.t21(0x22, 7, tHND); a.inv(0x70, g.M(HND, '<init>', '(Landroid/os/Looper;)V'), [7, 8])
    a.inv(0x6e, cap, [5, 4, 6, 7]); a.mr(0)
    sb_new(6); sb_s(6, 7, 'retry failed frame -> seq '); a.inv(0x6e, sbI, [6, 0]); log_sb(6); a.go('null')
    a.L('rt0')
    a.inv(0x71, getp, []); a.mro(1)
    a.c4(4, 1)                                                         # v4 = frames sent now (200 MP: 1)
    a.cs(2, S('TemporalBinning')); a.inv(0x72, mget, [1, 2]); a.mro(2); a.b21(0x39, 2, 'qgo')
    # PACE (50 MP): only PACE frames in flight; every finished remosaic sends the next one (see 'nx0' below), so the
    # vivo HAL never holds 15 queued full-size requests and the app holds ~PACE RAW buffers instead of the whole burst
    if PACE <= 0: a.go('null')
    a.cs(2, S('quadTo')); a.inv(0x72, mget, [1, 2]); a.mro(2); a.b21(0x38, 2, 'null')
    a.c4(4, PACE)
    # P287: the first 50/25 MP burst after an app start stalled twice (log d59cee74: no frame in 4 s, then the HAL
    #       closed the session). Warm-up: that burst sends one frame first; when it arrives,
    #       the next PACE frames go out together (TBramp), then the usual one-per-frame pacing.
    if __import__('os').environ.get('WARM1', '1') == '1' and PACE > 1:
        a.cs(2, S('TBwarm')); a.inv(0x72, mget, [1, 2]); a.mro(0); a.b21(0x39, 0, 'wm0')
        a.inv(0x72, mput, [1, 2, 2]); a.c4(4, 1)
        a.c4(0, PACE - 1); a.inv(0x71, ivo, [0]); a.mro(0); a.cs(2, S('TBramp')); a.inv(0x72, mput, [1, 2, 0])
        sb_new(6); sb_s(6, 7, 'warm-up: first burst after start, 1 frame first'); log_sb(6)
        a.L('wm0')
    a.L('qgo')
    a.c4(2, 4); a.raw(0x46 | 3 << 8, 12 | 2 << 8); a.t21(0x1f, 3, tINT); a.inv(0x6e, ivl, [3]); a.mr(3)   # v3 = n
    if int(__import__('os').environ.get('SETTLE', '300')) > 0:
        a.cs(7, S('TBREM')); a.inv(0x71, ivo, [3]); a.mro(0); a.inv(0x72, mput, [1, 7, 0])   # P239: frames left
        a.inv(0x71, g.M('LTBProg;', 'st', '()V'), [])                                     # P281: shutter ring
        a.inv(0x71, g.M('LTBWd;', 'arm', '(I)V'), [3])                                   # P283: burst watchdog
    MRG = int(__import__('os').environ.get('MRG', '1'))
    if MRG:   # P246: tell libtbin a burst of n frames starts; it merges them itself on the last one (merge.c)
        a.cs(0, S('nightS')); a.inv(0x72, mget, [1, 0]); a.mro(0); a.b21(0x38, 0, 'nk0')      # P261: night scale
        a.t21(0x1f, 0, tINT); a.inv(0x6e, ivl, [0]); a.mr(0); a.raw(0xd2 | 0 << 8 | 0 << 12, 1000); a.go('nk1')
        a.L('nk0'); a.c4(0, 0); a.L('nk1')
        a.raw(0xd0 | 0 << 8 | 0 << 12, int(__import__('os').environ.get('MRGK', '25')))
        a.cs(7, S('TB25')); a.inv(0x72, mget, [1, 7]); a.mro(7); a.b21(0x38, 7, 'nk2')                 # P271: 25 MP
        a.raw(0x14 | 7 << 8, 1000000 & 0xffff, 1000000 >> 16); a.raw(0xb0 | 0 << 8 | 7 << 12)
        a.L('nk2')
        a.inv(0x71, g.M(NCL, 'n', '(II)V'), [3, 0])
    a.b22(0x37, 3, 4, 'null')                                          # n <= v4 -> nothing to queue
    a.raw(0xb1 | 3 << 8 | 4 << 12)                                     # sub-int/2addr v3, v4
    a.inv(0x71, ivo, [3]); a.mro(5); a.raw(0x4d | 5 << 8, 12 | 2 << 8)  # aput-object v5, v12, v2(=4)
    a.cs(2, S('TBQ')); a.inv(0x72, mput, [1, 2, 12])
    sb_new(6); sb_s(6, 7, 'queue '); a.inv(0x6e, sbI, [6, 3]); log_sb(6)
    a.inv(0x71, ivo, [4]); a.mro(0); a.raw(0x0011)                     # return Integer(frames now)
    a.L('st')
    a.iof(0, 12, tSTR); a.b21(0x38, 0, 'cf')
    a.t21(0x1f, 12, tSTR); a.inv(0x71, ll, [12])
    # frame arrived: send the next queued capture
    a.inv(0x71, getp, []); a.mro(1)
    a.cs(2, S('TBQ')); a.inv(0x72, mget, [1, 2]); a.mro(12); a.b21(0x38, 12, 'null')
    a.t21(0x1f, 12, tOA)
    a.c4(9, 1)                                                          # P287: frames to send now
    a.cs(2, S('TBramp')); a.inv(0x72, mrem, [1, 2]); a.mro(10); a.b21(0x38, 10, 'rl0')
    a.t21(0x1f, 10, tINT); a.inv(0x6e, ivl, [10]); a.mr(9); a.raw(0xd8 | 9 << 8, 9 | 1 << 8)
    a.L('rl0')
    a.L('rloop')
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
    a.raw(0xd8 | 9 << 8, 9 | 0xff << 8); a.b21(0x3d, 9, 'null')        # P287: more to send now?
    a.cs(2, S('TBQ')); a.inv(0x72, mget, [1, 2]); a.mro(12); a.b21(0x38, 12, 'null'); a.t21(0x1f, 12, tOA)
    a.go('rloop')
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
    CR = 'Landroid/hardware/camera2/CaptureResult;'; KEY = 'Landroid/hardware/camera2/CaptureResult$Key;'
    # ---- AF trace (log build): every CaptureResult from Llei; logs when the AF/lens state tuple changes ----
    tCRS = g.T(CR); crg = g.M(CR, 'get', '(' + KEY + ')' + OBJ)
    a.iof(0, 12, tCRS); a.b21(0x38, 0, 'im0b')
    a.t21(0x1f, 12, tCRS)
    sb_new(6)
    for kn in ('CONTROL_AF_MODE', 'CONTROL_AF_STATE', 'CONTROL_AF_TRIGGER', 'LENS_STATE', 'CONTROL_AF_SCENE_CHANGE',
               'LENS_OPTICAL_STABILIZATION_MODE'):
        a.raw(0x62 | 0 << 8, g.Fd(CR, kn, KEY)); a.inv(0x6e, crg, [12, 0]); a.mro(1)
        sb_s(6, 7, ' ' + kn.replace('CONTROL_', '') + '='); a.inv(0x6e, sbo, [6, 1])
    a.inv(0x6e, sbt, [6]); a.mro(8)
    a.inv(0x71, getp, []); a.mro(10); a.cs(1, S('TBAF')); a.inv(0x72, mget, [10, 1]); a.mro(9)
    a.inv(0x6e, g.M(OBJ, 'equals', '(' + OBJ + ')Z'), [8, 9]); a.mr(0); a.b21(0x39, 0, 'null')
    a.inv(0x72, mput, [10, 1, 8])
    sb_new(6); sb_s(6, 7, 'AF'); a.inv(0x6e, sbs, [6, 8])
    tOA = g.T('[Ljava/lang/Object;'); atoo = g.M('Ljava/util/Arrays;', 'toString', '([Ljava/lang/Object;)' + STR)
    for kn in ('LENS_FOCUS_DISTANCE', 'LENS_FOCUS_RANGE', 'CONTROL_AE_STATE', 'SENSOR_EXPOSURE_TIME', 'SENSOR_SENSITIVITY',
               'SENSOR_FRAME_DURATION', 'CONTROL_AF_REGIONS', 'SENSOR_TIMESTAMP'):
        a.raw(0x62 | 0 << 8, g.Fd(CR, kn, KEY)); a.inv(0x6e, crg, [12, 0]); a.mro(1)
        a.iof(2, 1, tOA); a.b21(0x38, 2, 'af' + kn)
        a.t21(0x1f, 1, tOA); a.inv(0x71, atoo, [1]); a.mro(1)
        a.L('af' + kn); sb_s(6, 7, ' ' + kn + '='); a.inv(0x6e, sbo, [6, 1])
    log_sb(6); a.go('null')
    a.L('im0b')
    a.iof(0, 12, g.T('Lljm;')); a.b21(0x38, 0, 'im1')
    ld = g.M('Lljm;', 'd', '(' + KEY + ')' + OBJ)
    kname = g.M(KEY, 'getName', '()' + STR)
    atf = g.M('Ljava/util/Arrays;', 'toString', '([F)' + STR); ati = g.M('Ljava/util/Arrays;', 'toString', '([I)' + STR)
    tF = g.T('[F'); tI = g.T('[I')
    sb_new(6); sb_s(6, 7, 'meta')
    for kn in ('SENSOR_TIMESTAMP', 'SENSOR_SENSITIVITY', 'SENSOR_EXPOSURE_TIME', 'CONTROL_POST_RAW_SENSITIVITY_BOOST',
               'SENSOR_DYNAMIC_BLACK_LEVEL', 'SENSOR_DYNAMIC_WHITE_LEVEL', 'SCALER_CROP_REGION', 'SHADING_MODE',
               'STATISTICS_LENS_SHADING_MAP_MODE', 'SENSOR_NEUTRAL_COLOR_POINT', 'COLOR_CORRECTION_GAINS',
               'SENSOR_PIXEL_MODE', 'LENS_OPTICAL_STABILIZATION_MODE', 'STATISTICS_LENS_SHADING_CORRECTION_MAP', 'SENSOR_NOISE_PROFILE'):
        fk = g.Fd(CR, kn, KEY)
        a.raw(0x62 | 0 << 8, fk)                                    # sget-object v0, key
        sb_s(6, 7, ' ' + kn + '=')
        a.inv(0x72, ld, [12, 0]); a.mro(1)
        lab = 'k' + kn
        a.iof(2, 1, tF); a.b21(0x38, 2, lab + 'i')
        a.t21(0x1f, 1, tF); a.inv(0x71, atf, [1]); a.mro(1); a.go(lab)
        a.L(lab + 'i'); a.iof(2, 1, tI); a.b21(0x38, 2, lab + 'o')
        a.t21(0x1f, 1, tI); a.inv(0x71, ati, [1]); a.mro(1); a.go(lab)
        a.L(lab + 'o'); a.iof(2, 1, tOA); a.b21(0x38, 2, lab)
        a.t21(0x1f, 1, tOA); a.inv(0x71, atoo, [1]); a.mro(1)
        a.L(lab); a.inv(0x6e, sbo, [6, 1])
    a.inv(0x71, getp, []); a.mro(0)
    for k in ('TemporalBinning', 'AwbInfo_gains_get', 'AwbInfo_rgb2rgb_get', 'Landroid/hardware/camera2/params/LensShadingMap;'):
        sb_s(6, 7, ' P[' + k + ']='); a.cs(1, S(k)); a.inv(0x72, mget, [0, 1]); a.mro(1); a.inv(0x6e, sbo, [6, 1])
    log_sb(6); a.go('null')
    a.L('im1')
    a.iof(0, 12, tIMG); a.b21(0x39, 0, 'img')
    sb_new(6); sb_s(6, 7, 'obj '); a.inv(0x6e, sbo, [6, 12]); log_sb(6); a.go('null')
    a.L('img')
    a.t21(0x1f, 12, tIMG)
    a.inv(0x6e, gw, [12]); a.mr(2); a.inv(0x6e, gh, [12]); a.mr(3)
    a.inv(0x71, myl, []); a.mro(0); a.inv(0x71, mainl, []); a.mro(1)
    a.c16(4, 8192); a.b22(0x33, 2, 4, 'notq')
    a.b22(0x32, 0, 1, 'null'); a.go('quadimg')
    a.L('notq')
    sb_new(6); sb_s(6, 7, 'a w='); a.inv(0x6e, sbI, [6, 2]); sb_s(6, 7, ' h='); a.inv(0x6e, sbI, [6, 3])
    sb_s(6, 7, ' thread='); a.inv(0x6e, sbo, [6, 0]); sb_s(6, 7, ' '); a.inv(0x71, lm, []); a.mro(7); a.inv(0x6e, sbs, [6, 7]); log_sb(6)
    a.b22(0x32, 0, 1, 'null')                                   # main thread -> no binning
    a.c16(4, 16320); a.b22(0x33, 2, 4, 'null')
    a.inv(0x6e, gp, [12]); a.mro(0); a.c4(1, 0); a.raw(0x0046, 0x0100)
    a.inv(0x6e, grs, [0]); a.mr(1); a.inv(0x6e, gbuf, [0]); a.mro(0)
    a.c32(4, 100663296); a.inv(0x71, alloc, [4]); a.mro(4)
    # ISO of the viewfinder (stored by Llei) -> smooth weight t = clamp((ISO - 400) * 256 / 1200, 0, 256), kept in v12
    a.inv(0x71, getp, []); a.mro(5); a.cs(6, S('ISOSpeedLatitudezzz')); a.inv(0x72, mget, [5, 6]); a.mro(5)
    a.c4(6, 0)
    a.iof(7, 5, tINT); a.b21(0x38, 7, 'tset')
    a.t21(0x1f, 5, tINT); a.inv(0x6e, ivl, [5]); a.mr(6)
    a.L('tset')
    a.raw(0x00d0 | 6 << 8 | 6 << 12, (-400) & 0xffff)                   # add-int/lit16 v6, v6, -400
    a.raw(0x00d2 | 6 << 8 | 6 << 12, 256)                               # mul-int/lit16
    a.raw(0x00d3 | 6 << 8 | 6 << 12, 1200)                              # div-int/lit16
    a.b21(0x3b, 6, 'tpos'); a.c4(6, 0)
    a.L('tpos'); a.c16(7, 256); a.b22(0x37, 6, 7, 'tok'); a.c16(6, 256)
    a.L('tok')
    a.raw(0x0001 | 5 << 8 | 6 << 12)                                    # move v5, v6 (t)
    a.raw(0x0001 | 12 << 8 | 6 << 12)                                   # move v12, v6 (t, for the log)
    # viewfinder WB gains for Natural QB: v6 = R*1000 | B*1000 << 16
    a.inv(0x71, getp, []); a.mro(7); a.cs(8, S('AwbInfo_gains_get')); a.inv(0x72, mget, [7, 8]); a.mro(7)
    a.c4(6, 0)
    a.iof(8, 7, tRGB); a.b21(0x38, 8, 'wdone')
    a.t21(0x1f, 7, tRGB)
    a.c32(9, 0x447a0000)                                                 # 1000.0f
    a.inv(0x6e, gred, [7]); a.mr(8); a.raw(0x00c8 | 8 << 8 | 9 << 12); a.raw(0x0087 | 8 << 8 | 8 << 12); a.raw(0x0001 | 6 << 8 | 8 << 12)
    a.inv(0x6e, gblue, [7]); a.mr(8); a.raw(0x00c8 | 8 << 8 | 9 << 12); a.raw(0x0087 | 8 << 8 | 8 << 12)
    a.raw(0x00e0 | 8 << 8, 8 | 16 << 8)                                  # shl-int/lit8 v8, v8, 16
    a.raw(0x00b6 | 6 << 8 | 8 << 12)                                    # or-int/2addr v6, v8
    a.L('wdone')
    a.inv(0x71, nano, []); a.mrw(8)
    a.raw(0x0077 | 7 << 8, nb, 0)                                        # invoke-static/range {v0..v6}, N.b (prepare)
    a.mr(5)
    a.b21(0x39, 5, 'pfail')
    a.L('workers')
    # workers: availableProcessors() - 1 (max 7) threads + this thread
    a.inv(0x71, rtget, []); a.mro(6); a.inv(0x6e, rtcpu, [6]); a.mr(6)
    a.raw(0x00d8 | 6 << 8, 6 | 0xff << 8)                               # add-int/lit8 v6, v6, -1
    a.c4(7, 7); a.b22(0x37, 6, 7, 'c1'); a.c4(6, 7)
    a.L('c1'); a.b21(0x3b, 6, 'c2'); a.c4(6, 0)
    a.L('c2')
    a.raw(0x0023 | 7 << 8 | 6 << 12, tTHA)                              # new-array v7, v6, Thread[]
    a.c4(5, 0)
    a.L('l1'); a.b22(0x35, 5, 6, 'l1e')                                  # if-ge v5, v6
    a.t21(0x22, 2, tW); a.inv(0x70, winit, [2])
    a.t21(0x22, 3, tTH); a.inv(0x70, thinit, [3, 2]); a.inv(0x6e, thstart, [3])
    a.raw(0x004d | 3 << 8, 7 | 5 << 8)                                  # aput-object v3, v7, v5
    a.raw(0x00d8 | 5 << 8, 5 | 1 << 8); a.go('l1')
    a.L('l1e')
    a.inv(0x71, nw, [])
    a.c4(5, 0)
    a.L('l2'); a.b22(0x35, 5, 6, 'l2e')
    a.raw(0x0046 | 3 << 8, 7 | 5 << 8); a.inv(0x6e, thjoin, [3])
    a.raw(0x00d8 | 5 << 8, 5 | 1 << 8); a.go('l2')
    a.L('l2e')
    a.inv(0x71, nf, []); a.mr(5)
    a.inv(0x71, nano, []); a.mrw(10)
    a.raw(0x00bc | 10 << 8 | 8 << 12)
    sb_new(2); sb_s(2, 3, 'bin ns='); a.inv(0x6e, sbj, [2, 10, 11])
    sb_s(2, 3, ' ret='); a.inv(0x6e, sbI, [2, 5])
    sb_s(2, 3, ' t='); a.inv(0x6e, sbI, [2, 12])
    sb_s(2, 3, ' thr='); a.inv(0x6e, sbI, [2, 6]); sb_s(2, 3, ' '); a.inv(0x71, lm, []); a.mro(3); a.inv(0x6e, sbs, [2, 3])
    sb_s(2, 3, ' | '); a.inv(0x71, g.M(NCL, 's', '()' + STR), []); a.mro(3); a.inv(0x6e, sbs, [2, 3]); log_sb(2)
    # PACE (P226, removed in P227): sending the next capture from here deadlocks, GCam only starts processing after
    # the whole burst has arrived (P226 shots waited 10 s, then kept 3 frames). P227 sends it on frame arrival (W1).
    PACEBIN = False
    a.L('nx0')
    if PACEBIN:
        a.inv(0x71, getp, []); a.mro(1)
        a.cs(2, S('TBQ')); a.inv(0x72, mget, [1, 2]); a.mro(6); a.b21(0x38, 6, 'nx1')
        a.t21(0x1f, 6, tOA)
        a.c4(2, 4); a.raw(0x46 | 3 << 8, 6 | 2 << 8); a.t21(0x1f, 3, tINT); a.inv(0x6e, ivl, [3]); a.mr(3)
        a.b21(0x3d, 3, 'nxd')                                               # if-lez v3 -> drop the queue
        a.raw(0xd8 | 3 << 8, 3 | 0xff << 8)
        a.inv(0x71, ivo, [3]); a.mro(7); a.raw(0x4d | 7 << 8, 6 | 2 << 8)
        a.b21(0x39, 3, 'nxs'); a.cs(2, S('TBQ')); a.inv(0x72, mrem, [1, 2])
        a.L('nxs')
        a.c4(2, 0); a.raw(0x46 | 7 << 8, 6 | 2 << 8); a.t21(0x1f, 7, tSES)
        a.c4(2, 1); a.raw(0x46 | 8 << 8, 6 | 2 << 8); a.t21(0x1f, 8, tREQ)
        a.c4(2, 2); a.raw(0x46 | 9 << 8, 6 | 2 << 8); a.t21(0x1f, 9, tCB)
        a.c4(2, 3); a.raw(0x46 | 10 << 8, 6 | 2 << 8); a.t21(0x1f, 10, tHND)
        a.inv(0x6e, cap, [7, 8, 9, 10])
        sb_new(0); sb_s(0, 1, 'paced next left='); a.inv(0x6e, sbI, [0, 3]); log_sb(0)
        a.go('nx1')
        a.L('nxd'); a.cs(2, S('TBQ')); a.inv(0x72, mrem, [1, 2])
    a.L('nx1')
    a.raw(0x00d5 | 5 << 8 | 5 << 12, 0xff)                              # and-int/lit16 v5, v5, 0xff
    a.b21(0x39, 5, 'null')
    a.t21(0x22, 0, tLES); a.c16(1, 16384); a.c4(2, 2); a.c4(3, 0)
    a.inv(0x70, les, [0, 4, 1, 2, 3])
    a.t21(0x22, 1, tNNN); a.inv(0x70, nnn, [1]); a.inv(0x6e, nng, [1, 0])
    a.inv(0x6e, nnf, [1]); a.mro(0)
    a.inv(0x71, g.M(NCL, 'd', '()I'), []); a.mr(2); a.inv(0x71, ivo, [2]); a.mro(2)          # P271: frame size for Llet
    a.inv(0x71, getp, []); a.mro(3); a.cs(1, S('getWidth')); a.inv(0x72, mput, [3, 1, 2])
    a.L('t1')
    a.raw(0x0011)
    a.L('pfail')
    sb_new(2); sb_s(2, 3, 'prep rc='); a.inv(0x6e, sbI, [2, 5]); log_sb(2)
    a.L('null'); a.c4(0, 0); a.raw(0x0011)
    a.L('h')
    a.raw(0x000d | 0 << 8)                                      # move-exception v0
    sb_new(6); sb_s(6, 7, 'err '); a.inv(0x6e, sbo, [6, 0]); log_sb(6)
    a.c4(0, 0); a.raw(0x0011)
    if PVW:
        a.L('pvx')                                              # preview targets failed: burst goes on without them
        a.raw(0x000d | 1 << 8)                                  # (v0 = 'quadTo' id is still needed after pv1)
        sb_new(2); sb_s(2, 3, 'pvw err '); a.inv(0x6e, sbo, [2, 1]); log_sb(2)
        a.go('pv1')
    if PACEBIN:
        SUBTRY.append(('nx0', 'nx1', 'hx'))
        a.L('hx')                                               # paced send failed (session closed): keep the frame
        a.raw(0x000d | 0 << 8)
        sb_new(2); sb_s(2, 3, 'paced send err '); a.inv(0x6e, sbo, [2, 0]); log_sb(2)
        a.go('nx1')
    w = a.done(); L = a.lab
    tr = []; cur = L['t0']
    for st, en, hx in sorted(SUBTRY, key=lambda x: L[x[0]]):
        if L[st] > cur: tr.append((cur, L[st] - cur, L['h']))
        if L[en] > L[st]: tr.append((L[st], L[en] - L[st], L[hx]))
        cur = L[en]
    tr.append((cur, L['t1'] - cur, L['h']))
    code_a = (13, 1, 7, w, tr)

    clinit = (1, 0, 1, [0x1a | 0 << 8, S('tbin')] + [0x1071, loadl, 0] + [0x000e])

    g.cls('LTemporalBinning;', OBJ, 0x1, [('a', '(' + OBJ + ')' + OBJ, 0x9, code_a)])
    g.cls(NCL, OBJ, 0x1, [('<clinit>', '()V', 0x10008, clinit), ('b', '(' + BB + 'III' + BB + 'II)I', 0x109, None),
                          ('w', '()V', 0x109, None), ('f', '()I', 0x109, None),
                          ('q', '(' + BB + 'III' + BB + ')I', 0x109, None), ('a', '()' + BB, 0x109, None),
                          ('r', '(' + BB + ')I', 0x109, None), ('s', '()' + STR, 0x109, None),
                          ('n', '(II)V', 0x109, None), ('p', '(' + BB + 'I)I', 0x109, None), ('d', '()I', 0x109, None)])
    code_winit = (1, 1, 1, [0x1070, oinit, 0, 0x000e])
    code_wrun = (1, 1, 0, [0x0071, nw, 0, 0x000e])
    g.cls(WCL, OBJ, 0x1, [('<init>', '()V', 0x10001, code_winit)], [('run', '()V', 0x1, code_wrun)], [RUN])
    # ---- P275/P279: per-mode settings profiles + bundle. Class 'getWidth' (a name that exists as a string in classes2
    #      and classes.dex), a Comparator reached via Class.forName + newInstance + compare(Integer code, null):
    #      0..2 save settings (without bundle keys) as /LMC8.3/XML/auto/<12|50|25>.xml (mode being left);
    #      10..12 plan that mode's profile; 99 (LMC main.onRestart, RES switch) put the planned profile in place;
    #      98 (double-tap Import restart) unpack the imported file's bundle into auto/. At 98 / 99 the three profiles are
    #      embedded into the settings file as <string name="xfrb_NN">base64</string>, so an LMC "Save XML" carries all three. ----
    FILE = 'Ljava/io/File;'; PATHT = 'Ljava/nio/file/Path;'; FILES = 'Ljava/nio/file/Files;'; CTXT = 'Landroid/content/Context;'
    PW = 'LgetWidth;'; B64 = 'Landroid/util/Base64;'; PAT = 'Ljava/util/regex/Pattern;'; MAT = 'Ljava/util/regex/Matcher;'
    m_rd = g.M(PW, 'rd', '(' + STR + ')' + STR); m_wr = g.M(PW, 'wr', '(' + STR + '[B)V'); m_st = g.M(PW, 'st', '(' + STR + ')' + STR)
    m_inj = g.M(PW, 'inj', '(' + STR + STR + ')' + STR); m_unp = g.M(PW, 'unp', '(' + STR + STR + ')I')
    newf = g.M(FILE, '<init>', '(' + STR + ')V'); topath = g.M(FILE, 'toPath', '()' + PATHT)
    gbytes = g.M(STR, 'getBytes', '()[B'); snew = g.M(STR, '<init>', '([B)V')
    # rd(v4 this, v5 path) -> String or null
    a = A()
    a.b21(0x38, 5, 'nul')
    a.t21(0x22, 0, g.T(FILE)); a.inv(0x70, newf, [0, 5]); a.inv(0x6e, g.M(FILE, 'exists', '()Z'), [0]); a.mr(1); a.b21(0x38, 1, 'nul')
    a.inv(0x6e, topath, [0]); a.mro(0); a.inv(0x71, g.M(FILES, 'readAllBytes', '(' + PATHT + ')[B'), [0]); a.mro(1)
    a.t21(0x22, 0, g.T(STR)); a.inv(0x70, snew, [0, 1]); a.raw(0x11 | 0 << 8)
    a.L('nul'); a.c4(0, 0); a.raw(0x11 | 0 << 8)
    code_rd = (6, 2, 2, a.done())
    # wr(v3 this, v4 path, v5 bytes)
    a = A()
    a.t21(0x22, 0, g.T(FILE)); a.inv(0x70, newf, [0, 4]); a.inv(0x6e, topath, [0]); a.mro(0)
    a.c4(1, 0); a.raw(0x23 | 1 << 8 | 1 << 12, g.T('[Ljava/nio/file/OpenOption;'))
    a.inv(0x71, g.M(FILES, 'write', '(' + PATHT + '[B[Ljava/nio/file/OpenOption;)' + PATHT), [0, 5, 1]); a.raw(0x000e)
    code_wr = (6, 3, 3, a.done())
    # st(v3 this, v4 s): remove bundle entries
    a = A()
    a.cs(0, S('<string name="xfrb_[^"]*">[^<]*</string>\\s*')); a.cs(1, S(''))
    a.inv(0x6e, g.M(STR, 'replaceAll', '(' + STR + STR + ')' + STR), [4, 0, 1]); a.mro(0); a.raw(0x11 | 0 << 8)
    code_st = (5, 2, 3, a.done())
    # inj(v8 this, v9 s, v10 dir): s with the three profiles embedded before </map>
    a = A()
    sb_new(0)
    for nm in ('12', '50', '25'):
        sb_new(1); a.inv(0x6e, sbs, [1, 10]); sb_s(1, 2, nm + '.xml'); a.inv(0x6e, sbt, [1]); a.mro(1)
        a.inv(0x70, m_rd, [8, 1]); a.mro(1); a.b21(0x38, 1, 'sk' + nm)
        a.inv(0x70, m_st, [8, 1]); a.mro(1); a.inv(0x6e, gbytes, [1]); a.mro(1)
        a.c4(2, 2); a.inv(0x71, g.M(B64, 'encodeToString', '([BI)' + STR), [1, 2]); a.mro(1)
        sb_s(0, 2, '<string name="xfrb_' + nm + '">'); a.inv(0x6e, sbs, [0, 1]); sb_s(0, 2, '</string>\n')
        a.L('sk' + nm)
    sb_s(0, 2, '</map>'); a.inv(0x6e, sbt, [0]); a.mro(0)
    a.cs(1, S('</map>')); a.inv(0x6e, g.M(STR, 'replace', '(Ljava/lang/CharSequence;Ljava/lang/CharSequence;)' + STR), [9, 1, 0]); a.mro(0)
    a.raw(0x11 | 0 << 8)
    code_inj = (11, 3, 3, a.done())
    # unp(v8 this, v9 s, v10 dir) -> count: every xfrb_NN entry decoded to dir/NN.xml
    a = A()
    a.cs(0, S('<string name="xfrb_(\\d+)">([^<]*)</string>')); a.inv(0x71, g.M(PAT, 'compile', '(' + STR + ')' + PAT), [0]); a.mro(0)
    a.inv(0x6e, g.M(PAT, 'matcher', '(Ljava/lang/CharSequence;)' + MAT), [0, 9]); a.mro(0)
    a.c4(5, 0)
    a.L('lp'); a.inv(0x6e, g.M(MAT, 'find', '()Z'), [0]); a.mr(1); a.b21(0x38, 1, 'end')
    a.c4(1, 1); a.inv(0x6e, g.M(MAT, 'group', '(I)' + STR), [0, 1]); a.mro(1)
    a.c4(2, 2); a.inv(0x6e, g.M(MAT, 'group', '(I)' + STR), [0, 2]); a.mro(2)
    a.c4(3, 0); a.inv(0x71, g.M(B64, 'decode', '(' + STR + 'I)[B'), [2, 3]); a.mro(2)
    sb_new(3); a.inv(0x6e, sbs, [3, 10]); a.inv(0x6e, sbs, [3, 1]); sb_s(3, 4, '.xml'); a.inv(0x6e, sbt, [3]); a.mro(3)
    a.inv(0x70, m_wr, [8, 3, 2]); a.raw(0xd8 | 5 << 8, 5 | 1 << 8); a.go('lp')
    a.L('end'); a.raw(0x0f | 5 << 8)
    code_unp = (11, 3, 3, a.done())
    # compare(v10 this, v11 code, v12 unused): v0..v9 locals
    a = A()
    a.L('t0')
    a.iof(0, 11, g.T('Ljava/lang/Float;')); a.b21(0x39, 0, 'isflt')                           # P285: night key
    a.iof(0, 11, tINT); a.b21(0x39, 0, 'isint')
    SDF = 'Ljava/text/SimpleDateFormat;'
    a.iof(0, 11, g.T(SDF)); a.b21(0x39, 0, 'issdf')
    a.inv(0x71, getp, []); a.mro(4); a.cs(5, S('TBSPO')); a.inv(0x72, mput, [4, 5, 11])          # P281: GCam's shutter ring
    sb_new(4); sb_s(4, 5, 'shutter ring overlay registered'); log_sb(4); a.go('ret')
    a.L('issdf')
    a.t21(0x1f, 11, g.T(SDF)); a.inv(0x6e, g.M(SDF, 'toPattern', '()' + STR), [11]); a.mro(1)
    a.raw(0x62 | 2 << 8, g.Fd('Ljava/util/Locale;', 'US', 'Ljava/util/Locale;'))
    a.t21(0x22, 3, g.T('LTBDF;')); a.inv(0x70, g.M('LTBDF;', '<init>', '(' + STR + 'Ljava/util/Locale;)V'), [3, 1, 2])
    a.inv(0x71, getp, []); a.mro(4); a.inv(0x72, mput, [4, 11, 3])
    sb_new(4); sb_s(4, 5, 'file name tagger on: '); a.inv(0x6e, sbs, [4, 1]); log_sb(4); a.go('ret')
    # ---- P285: night key (RawR idea): shot EV (Float, from AeShotParams.g) -> (EV + off) x 1000.
    #      EV100 = log2(N^2 x 100 / (t x ISO)) of the last viewfinder frame; off = -NIGHTKEY x smoothstep((NIGHTEV - EV100)
    #      / NIGHTEV), not below -NIGHTCAP. Missing viewfinder data -> EV unchanged ----
    a.L('isflt')
    _f = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
    def cf(r, x): v = _f(x); a.raw(0x14 | r << 8, v & 0xffff, v >> 16)
    NK = float(os.environ.get('NIGHTKEY', '1.7')); NC = float(os.environ.get('NIGHTCAP', '1.0')); NE = float(os.environ.get('NIGHTEV', '10.0'))
    FN = float(os.environ.get('NIGHTFN', '1.85'))
    a.t21(0x1f, 11, g.T('Ljava/lang/Float;')); a.inv(0x6e, g.M('Ljava/lang/Float;', 'floatValue', '()F'), [11]); a.mr(0)
    a.inv(0x71, getp, []); a.mro(8)
    a.cs(9, S('ISOSpeedLatitudezzz')); a.inv(0x72, mget, [8, 9]); a.mro(1); a.iof(2, 1, tINT); a.b21(0x38, 2, 'fret')
    a.t21(0x1f, 1, tINT); a.inv(0x6e, ivl, [1]); a.mr(1)
    a.c4(2, 0); a.b22(0x37, 1, 2, 'fret')                                                     # ISO <= 0
    a.cs(9, S('ExposureTime')); a.inv(0x72, mget, [8, 9]); a.mro(2); a.iof(3, 2, g.T('Ljava/lang/Long;')); a.b21(0x38, 3, 'fret')
    a.t21(0x1f, 2, g.T('Ljava/lang/Long;')); a.inv(0x6e, g.M('Ljava/lang/Long;', 'longValue', '()J'), [2]); a.mrw(2)
    a.raw(0x86 | 2 << 8 | 2 << 12); a.raw(0x83 | 4 << 8 | 1 << 12)                           # v2 = t (double), v4 = ISO
    a.raw(0xcd | 2 << 8 | 4 << 12)                                                             # v2 = t x ISO
    kd = struct.unpack('<Q', struct.pack('<d', FN * FN * 100.0 * 1e9))[0]
    a.raw(0x18 | 4 << 8, kd & 0xffff, (kd >> 16) & 0xffff, (kd >> 32) & 0xffff, kd >> 48)
    a.raw(0xce | 4 << 8 | 2 << 12)                                                             # v4 = N^2 100 / (t ISO)
    a.inv(0x71, g.M('Ljava/lang/Math;', 'log', '(D)D'), [4, 5]); a.mrw(4)
    l2 = struct.unpack('<Q', struct.pack('<d', 0.6931471805599453))[0]
    a.raw(0x18 | 6 << 8, l2 & 0xffff, (l2 >> 16) & 0xffff, (l2 >> 32) & 0xffff, l2 >> 48)
    a.raw(0xce | 4 << 8 | 6 << 12); a.raw(0x8c | 1 << 8 | 4 << 12)                           # v1 = EV100 (float)
    cf(2, NE); a.raw(0xa7 | 3 << 8, 2 | 1 << 8); a.raw(0xc9 | 3 << 8 | 2 << 12)              # v3 = (NE - EV100) / NE
    cf(2, 0.0); a.raw(0x2d | 4 << 8, 3 | 2 << 8); a.b21(0x3b, 4, 'nk1'); a.raw(0x01 | 3 << 8 | 2 << 12)
    a.L('nk1'); cf(2, 1.0); a.raw(0x2e | 4 << 8, 3 | 2 << 8); a.b21(0x3d, 4, 'nk2'); a.raw(0x01 | 3 << 8 | 2 << 12)
    a.L('nk2'); cf(2, 2.0); a.raw(0xa8 | 4 << 8, 3 | 2 << 8); cf(2, 3.0); a.raw(0xa7 | 4 << 8, 2 | 4 << 8)   # v4 = 3 - 2x
    a.raw(0xc8 | 4 << 8 | 3 << 12); a.raw(0xc8 | 4 << 8 | 3 << 12)                           # v4 = smoothstep
    cf(2, -NK); a.raw(0xc8 | 4 << 8 | 2 << 12)                                                 # v4 = off
    cf(2, -NC); a.raw(0x2d | 5 << 8, 4 | 2 << 8); a.b21(0x3b, 5, 'nk3'); a.raw(0x01 | 4 << 8 | 2 << 12)
    a.L('nk3')
    sb_new(8); sb_s(8, 9, 'night key ev100='); a.inv(0x6e, g.M(SB, 'append', '(F)' + SB), [8, 1])
    sb_s(8, 9, ' off='); a.inv(0x6e, g.M(SB, 'append', '(F)' + SB), [8, 4])
    sb_s(8, 9, ' user ev='); a.inv(0x6e, g.M(SB, 'append', '(F)' + SB), [8, 0]); log_sb(8)
    a.raw(0xc6 | 0 << 8 | 4 << 12)                                                             # ev += off
    a.L('fret'); cf(2, 1000.0); a.raw(0xc8 | 0 << 8 | 2 << 12); a.raw(0x87 | 0 << 8 | 0 << 12); a.raw(0x0f | 0 << 8)
    a.L('isint')
    a.t21(0x1f, 11, tINT); a.inv(0x6e, ivl, [11]); a.mr(0)
    a.inv(0x71, g.M('Landroid/app/AppGlobals;', 'getInitialApplication', '()Landroid/app/Application;'), []); a.mro(1)
    a.inv(0x6e, g.M(CTXT, 'getFilesDir', '()' + FILE), [1]); a.mro(2)
    a.inv(0x6e, g.M(FILE, 'getParent', '()' + STR), [2]); a.mro(2)
    a.inv(0x71, g.M('Landroid/preference/PreferenceManager;', 'getDefaultSharedPreferencesName', '(' + CTXT + ')' + STR), [1]); a.mro(3)
    sb_new(4); a.inv(0x6e, sbs, [4, 2]); sb_s(4, 5, '/shared_prefs/'); a.inv(0x6e, sbs, [4, 3]); sb_s(4, 5, '.xml')
    a.inv(0x6e, sbt, [4]); a.mro(2)                                                          # v2 = settings file
    a.inv(0x71, g.M('Landroid/os/Environment;', 'getExternalStorageDirectory', '()' + FILE), []); a.mro(3)
    sb_new(4); a.inv(0x6e, sbo, [4, 3]); sb_s(4, 5, '/LMC8.3/XML/auto/'); a.inv(0x6e, sbt, [4]); a.mro(3)   # v3 = dir
    a.t21(0x22, 4, g.T(FILE)); a.inv(0x70, newf, [4, 3]); a.inv(0x6e, g.M(FILE, 'mkdirs', '()Z'), [4])
    a.c16(4, 99); a.b22(0x32, 0, 4, 'commit')
    a.c16(4, 98); a.b22(0x32, 0, 4, 'imp')
    a.c16(4, 96); a.b22(0x34, 0, 4, 'ntap')                                                 # P282: 96 / 97 shutter tap log
    a.c16(4, 98); a.b22(0x35, 0, 4, 'ntap')
    sb_new(4); sb_s(4, 6, 'shutter tap'); a.c16(5, 97); a.b22(0x32, 0, 5, 'tapok'); sb_s(4, 6, ' BLOCKED (camera busy)')
    a.L('tapok'); log_sb(4); a.go('ret')
    a.L('ntap')
    a.raw(0xdc | 4 << 8, 0 | 10 << 8)                                                       # rem-int/lit8 v4, v0, 10
    a.cs(6, S('12')); a.c4(7, 1); a.b22(0x33, 4, 7, 'n1'); a.cs(6, S('50'))
    a.L('n1'); a.c4(7, 2); a.b22(0x33, 4, 7, 'n2'); a.cs(6, S('25'))
    a.L('n2')
    sb_new(5); a.inv(0x6e, sbs, [5, 3]); a.inv(0x6e, sbs, [5, 6]); sb_s(5, 7, '.xml'); a.inv(0x6e, sbt, [5]); a.mro(5)
    a.c16(4, 10); a.b22(0x35, 0, 4, 'plan')
    # save: settings (bundle removed) -> profile
    a.inv(0x70, m_rd, [10, 2]); a.mro(7); a.b21(0x38, 7, 'ret')
    a.inv(0x70, m_st, [10, 7]); a.mro(7); a.inv(0x6e, gbytes, [7]); a.mro(7); a.inv(0x70, m_wr, [10, 5, 7])
    sb_new(4); sb_s(4, 6, 'profile saved '); a.inv(0x6e, sbs, [4, 5]); log_sb(4)
    a.go('ret')
    a.L('plan')
    a.inv(0x71, getp, []); a.mro(4); a.cs(6, S('TBXPLAN')); a.inv(0x72, mput, [4, 6, 5])
    sb_new(4); sb_s(4, 6, 'profile planned '); a.inv(0x6e, sbs, [4, 5]); log_sb(4)
    a.go('ret')
    a.L('commit')                                                                            # base = planned profile, else settings
    a.inv(0x71, getp, []); a.mro(4); a.cs(6, S('TBXPLAN')); a.inv(0x72, mrem, [4, 6]); a.mro(5)
    a.c4(7, 0); a.b21(0x38, 5, 'cb'); a.t21(0x1f, 5, g.T(STR)); a.inv(0x70, m_rd, [10, 5]); a.mro(7)
    a.L('cb'); a.b21(0x39, 7, 'cb2'); a.inv(0x70, m_rd, [10, 2]); a.mro(7); a.b21(0x38, 7, 'ret')
    a.L('cb2'); a.c4(8, 0); a.go('fin')
    a.L('imp'); a.c4(5, 0)
    a.raw(0x16 | 8 << 8, 400); a.inv(0x71, g.M('Ljava/lang/Thread;', 'sleep', '(J)V'), [8, 9])   # let LMC's async prefs write land first
    a.inv(0x70, m_rd, [10, 2]); a.mro(7); a.b21(0x38, 7, 'ret')
    a.inv(0x70, m_unp, [10, 7, 3]); a.mr(8)
    a.L('fin')                                                                               # v7 base, v8 unpacked count
    a.inv(0x70, m_st, [10, 7]); a.mro(7); a.inv(0x70, m_inj, [10, 7, 3]); a.mro(7)
    a.inv(0x6e, gbytes, [7]); a.mro(9); a.inv(0x70, m_wr, [10, 2, 9])
    sb_new(4); sb_s(4, 6, 'profile commit code='); a.inv(0x6e, sbI, [4, 0]); sb_s(4, 6, ' unpacked='); a.inv(0x6e, sbI, [4, 8])
    sb_s(4, 6, ' bytes='); a.raw(0x21 | 9 << 8 | 9 << 12); a.inv(0x6e, sbI, [4, 9]); sb_s(4, 6, ' base='); a.inv(0x6e, sbo, [4, 5]); log_sb(4)
    a.L('ret'); a.L('t1'); a.c4(0, 0); a.raw(0x0f | 0 << 8)
    a.L('h'); a.raw(0x0d | 0 << 8)
    sb_new(4); sb_s(4, 6, 'profile err '); a.inv(0x6e, sbo, [4, 0]); log_sb(4)
    a.c4(0, 0); a.raw(0x0f | 0 << 8)
    w = a.done(); L = a.lab
    code_cmp = (13, 3, 4, w, [(L['t0'], L['t1'] - L['t0'], L['h'])])
    code_pinit = (1, 1, 1, [0x1070, oinit, 0, 0x000e])
    # ---- P277: gyro steadiness -> longer frames when the phone is still. LTBGyro listens to the gyroscope
    #      (SENSOR_DELAY_GAME), keeps an average angular speed (rad/s) in props 'TBgyro'. LTBGyro.s() at each new shot:
    #      speed < threshold (tele / teleconverter stricter) -> 'TBlong' = LONGEXP2, else LONGEXP. ----
    import os as _os
    GYC = 'LTBGyro;'; SEV = 'Landroid/hardware/SensorEvent;'; FLT = 'Ljava/lang/Float;'
    L1 = int(_os.environ.get('LONGEXP', '30000000')); L2 = int(_os.environ.get('LONGEXP2', '40000000'))   # P283: 60 ms without OIS stalled a 50 MP burst
    GTM = float(_os.environ.get('GYROTM', '0.015')); GTT = float(_os.environ.get('GYROTT', '0.006'))
    fbits = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
    fv = g.Fd(GYC, 'v', 'F'); fvo = g.M(FLT, 'valueOf', '(F)' + FLT); ffv = g.M(FLT, 'floatValue', '()F')
    a = A()                                       # onSensorChanged(v8 this, v9 event)
    a.raw(0x54 | 0 << 8 | 9 << 12, g.Fd(SEV, 'values', '[F'))
    a.c4(2, 0); a.raw(0x44 | 1 << 8, 0 | 2 << 8); a.raw(0xc8 | 1 << 8 | 1 << 12)
    a.c4(3, 1); a.raw(0x44 | 2 << 8, 0 | 3 << 8); a.raw(0xc8 | 2 << 8 | 2 << 12); a.raw(0xc6 | 1 << 8 | 2 << 12)
    a.c4(3, 2); a.raw(0x44 | 2 << 8, 0 | 3 << 8); a.raw(0xc8 | 2 << 8 | 2 << 12); a.raw(0xc6 | 1 << 8 | 2 << 12)
    a.raw(0x89 | 2 << 8 | 1 << 12)                                                    # v2:v3 = (double) v1
    a.inv(0x71, g.M('Ljava/lang/Math;', 'sqrt', '(D)D'), [2, 3]); a.mrw(2); a.raw(0x8c | 1 << 8 | 2 << 12)
    a.raw(0x52 | 2 << 8 | 8 << 12, fv)
    b9 = fbits(0.9); b1 = fbits(0.1)
    a.raw(0x14 | 3 << 8, b9 & 0xffff, b9 >> 16); a.raw(0xc8 | 2 << 8 | 3 << 12)
    a.raw(0x14 | 3 << 8, b1 & 0xffff, b1 >> 16); a.raw(0xc8 | 1 << 8 | 3 << 12); a.raw(0xc6 | 2 << 8 | 1 << 12)
    a.raw(0x59 | 2 << 8 | 8 << 12, fv)
    a.inv(0x71, getp, []); a.mro(4); a.cs(5, S('TBgyro')); a.inv(0x71, fvo, [2]); a.mro(6); a.inv(0x72, mput, [4, 5, 6])
    a.raw(0x000e)
    code_gsc = (10, 2, 3, a.done())
    code_gacc = (3, 3, 0, [0x000e])
    a = A()                                       # static s(): v0..v9
    a.L('t0')
    a.inv(0x71, getp, []); a.mro(0)
    a.cs(1, S('TBgyroR')); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [0, 1]); a.mro(2); a.b21(0x39, 2, 'reg1')
    a.inv(0x71, g.M('Landroid/app/AppGlobals;', 'getInitialApplication', '()Landroid/app/Application;'), []); a.mro(2)
    a.cs(3, S('sensor')); a.inv(0x6e, g.M('Landroid/content/Context;', 'getSystemService', '(' + STR + ')' + OBJ), [2, 3]); a.mro(2)
    SMG = 'Landroid/hardware/SensorManager;'; SNS = 'Landroid/hardware/Sensor;'
    a.t21(0x1f, 2, g.T(SMG)); a.c4(3, 4); a.inv(0x6e, g.M(SMG, 'getDefaultSensor', '(I)' + SNS), [2, 3]); a.mro(3)
    a.b21(0x38, 3, 'reg1')
    a.t21(0x22, 4, g.T(GYC)); a.inv(0x70, g.M(GYC, '<init>', '()V'), [4])
    a.c4(5, 1); a.inv(0x6e, g.M(SMG, 'registerListener', '(Landroid/hardware/SensorEventListener;' + SNS + 'I)Z'), [2, 4, 3, 5])
    a.inv(0x72, mput, [0, 1, 4])
    sb_new(6); sb_s(6, 7, 'gyro listener on'); log_sb(6)
    a.L('reg1')
    a.raw(0x14 | 4 << 8, 0, 0x3f80)                                                   # v4 = 1.0 (no data: moving)
    a.cs(1, S('TBgyro')); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [0, 1]); a.mro(2); a.b21(0x38, 2, 'nod')
    a.t21(0x1f, 2, g.T(FLT)); a.inv(0x6e, ffv, [2]); a.mr(4)
    a.L('nod')
    bt = fbits(GTM); a.raw(0x14 | 5 << 8, bt & 0xffff, bt >> 16)
    a.cs(1, QKEY); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [0, 1]); a.mro(2)
    a.cs(3, S('5')); a.inv(0x6e, g.M(STR, 'equals', '(' + OBJ + ')Z'), [3, 2]); a.mr(3); a.b21(0x38, 3, 'thm')
    bt = fbits(GTT); a.raw(0x14 | 5 << 8, bt & 0xffff, bt >> 16)
    a.L('thm')
    HH = int(_os.environ.get('HHEXP', '20000000'))                                    # P286: handheld cap 1/50 s (idea: Ray)
    LM = HH if HH > 0 else L1
    a.raw(0x17 | 6 << 8, LM & 0xffff, LM >> 16)
    a.raw(0x2d | 3 << 8, 4 | 5 << 8); a.b21(0x3b, 3, 'mov')                           # cmpl-float: v4 >= thr -> moving
    a.raw(0x17 | 6 << 8, L2 & 0xffff, L2 >> 16)
    a.cs(1, S('TBhh')); a.inv(0x72, g.M('Ljava/util/Map;', 'remove', '(' + OBJ + ')' + OBJ), [0, 1]); a.go('mv2')
    a.L('mov')
    if HH > 0: a.cs(1, S('TBhh')); a.inv(0x72, mput, [0, 1, 1])                      # P286: handheld flag
    a.L('mv2')
    a.inv(0x71, g.M(LNG, 'valueOf', '(J)' + LNG), [6, 7]); a.mro(2); a.cs(1, S('TBlong')); a.inv(0x72, mput, [0, 1, 2])
    sb_new(8); sb_s(8, 9, 'gyro v='); a.inv(0x6e, g.M(SB, 'append', '(F)' + SB), [8, 4]); sb_s(8, 9, ' thr=')
    a.inv(0x6e, g.M(SB, 'append', '(F)' + SB), [8, 5]); sb_s(8, 9, ' maxexp='); a.inv(0x6e, sbj, [8, 6, 7]); log_sb(8)
    a.L('t1'); a.raw(0x000e)
    a.L('h'); a.raw(0x0d | 0 << 8); sb_new(8); sb_s(8, 9, 'gyro err '); a.inv(0x6e, sbo, [8, 0]); log_sb(8); a.raw(0x000e)
    w = a.done(); Lb = a.lab
    code_gs = (10, 0, 4, w, [(Lb['t0'], Lb['t1'] - Lb['t0'], Lb['h'])])
    g.cls(GYC, OBJ, 0x1, [('<init>', '()V', 0x10001, code_pinit), ('s', '()V', 0x9, code_gs)],
          [('onSensorChanged', '(' + SEV + ')V', 0x1, code_gsc), ('onAccuracyChanged', '(' + SNS + 'I)V', 0x1, code_gacc)],
          ['Landroid/hardware/SensorEventListener;'], [('v', 'F')])
    # ---- P281: RawR-like progress ring around the shutter for 50 / 25 MP bursts, drawn by GCam's own
    #      ShutterButtonProgressOverlay (the Night Sight ring): st() at burst start -> intro, then a smooth sweep over
    #      the expected burst time (last measured, 2 s at first); en() on the last frame -> ring completes and fades. ----
    PRG = 'LTBProg;'; SPO = 'Lcom/google/android/apps/camera/ui/shutterbutton/ShutterButtonProgressOverlay;'
    VIEW = 'Landroid/view/View;'; MTH = 'Ljava/lang/reflect/Method;'; CLSs = 'Ljava/lang/Class;'
    fpm = g.Fd(PRG, 'm', 'I'); fpt = g.Fd(PRG, 't', 'J'); prinit = g.M(PRG, '<init>', '(IJ)V')
    mget_ = g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ)
    code_pri = (4, 4, 1, [0x1070, oinit, 0, 0x0159 | 0, fpm, 0x025a, fpt, 0x000e])
    a = A()                                              # run(v8 this)
    a.L('t0')
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, S('TBSPO')); a.inv(0x72, mget_, [0, 1]); a.mro(1); a.b21(0x38, 1, 'ret')
    a.inv(0x6e, g.M(OBJ, 'getClass', '()' + CLSs), [1]); a.mro(2)
    a.c4(3, 3); a.raw(0x23 | 3 << 8 | 3 << 12, g.T('[' + CLSs))
    a.raw(0x62 | 4 << 8, g.Fd('Ljava/lang/Integer;', 'TYPE', CLSs)); a.c4(5, 0); a.raw(0x4d | 4 << 8, 3 | 5 << 8)
    a.raw(0x62 | 4 << 8, g.Fd(LNG, 'TYPE', CLSs)); a.c4(5, 1); a.raw(0x4d | 4 << 8, 3 | 5 << 8)
    a.raw(0x62 | 4 << 8, g.Fd('Ljava/lang/Boolean;', 'TYPE', CLSs)); a.c4(5, 2); a.raw(0x4d | 4 << 8, 3 | 5 << 8)
    a.cs(4, S('b')); a.inv(0x6e, g.M(CLSs, 'getDeclaredMethod', '(' + STR + '[' + CLSs + ')' + MTH), [2, 4, 3]); a.mro(2)
    a.c4(4, 1); a.inv(0x6e, g.M(MTH, 'setAccessible', '(Z)V'), [2, 4])
    a.raw(0x52 | 4 << 8 | 8 << 12, fpm)                                              # v4 = mode
    a.c4(5, 0); a.raw(0x16 | 6 << 8, 0xffff)                                         # v5 = 0 %, v6:v7 = -1
    a.b21(0x38, 4, 'go')
    a.c4(5, 1); a.raw(0x53 | 6 << 8 | 8 << 12, fpt); a.c4(3, 1); a.b22(0x32, 4, 3, 'go')   # mode 1: 1 %, duration t
    a.c16(5, 100); a.raw(0x16 | 6 << 8, 0xffff)                                      # mode 2: 100 % -> fade out
    a.L('go')
    a.c4(3, 3); a.raw(0x23 | 3 << 8 | 3 << 12, g.T('[' + OBJ))
    a.inv(0x71, ivo, [5]); a.mro(4); a.c4(5, 0); a.raw(0x4d | 4 << 8, 3 | 5 << 8)
    a.inv(0x71, g.M(LNG, 'valueOf', '(J)' + LNG), [6, 7]); a.mro(4); a.c4(5, 1); a.raw(0x4d | 4 << 8, 3 | 5 << 8)
    a.raw(0x62 | 4 << 8, g.Fd('Ljava/lang/Boolean;', 'FALSE', 'Ljava/lang/Boolean;')); a.c4(5, 2); a.raw(0x4d | 4 << 8, 3 | 5 << 8)
    a.inv(0x6e, g.M(MTH, 'invoke', '(' + OBJ + '[' + OBJ + ')' + OBJ), [2, 1, 3])
    a.L('ret'); a.L('t1'); a.raw(0x000e)
    a.L('h'); a.raw(0x0d | 0 << 8); sb_new(4); sb_s(4, 5, 'ring err '); a.inv(0x6e, sbo, [4, 0]); log_sb(4); a.raw(0x000e)
    w = a.done(); Lb = a.lab
    code_prun = (9, 1, 4, w, [(Lb['t0'], Lb['t1'] - Lb['t0'], Lb['h'])])
    a = A()                                              # static st(): v0..v7
    a.inv(0x71, getp, []); a.mro(0)
    a.inv(0x71, g.M('Ljava/lang/System;', 'currentTimeMillis', '()J'), []); a.mrw(2)
    a.inv(0x71, g.M(LNG, 'valueOf', '(J)' + LNG), [2, 3]); a.mro(4); a.cs(1, S('TBR0')); a.inv(0x72, mput, [0, 1, 4])
    a.raw(0x17 | 2 << 8, 2000, 0)                                                    # est = 2000 ms
    a.cs(1, S('TBRMS')); a.inv(0x72, mget_, [0, 1]); a.mro(4); a.iof(5, 4, g.T(LNG)); a.b21(0x38, 5, 'e0')
    a.t21(0x1f, 4, g.T(LNG)); a.inv(0x6e, g.M(LNG, 'longValue', '()J'), [4]); a.mrw(2)
    a.L('e0')
    a.cs(1, S('TBSPO')); a.inv(0x72, mget_, [0, 1]); a.mro(1); a.iof(5, 1, g.T(VIEW)); a.b21(0x38, 5, 'x')
    a.t21(0x1f, 1, g.T(VIEW))
    a.t21(0x22, 4, g.T(PRG)); a.c4(5, 0); a.raw(0x16 | 6 << 8, 0); a.inv(0x70, prinit, [4, 5, 6, 7])
    a.inv(0x6e, g.M(VIEW, 'post', '(Ljava/lang/Runnable;)Z'), [1, 4])
    a.t21(0x22, 4, g.T(PRG)); a.c4(5, 1); a.inv(0x70, prinit, [4, 5, 2, 3])
    a.raw(0x16 | 6 << 8, 130); a.inv(0x6e, g.M(VIEW, 'postDelayed', '(Ljava/lang/Runnable;J)Z'), [1, 4, 6, 7])
    sb_new(4); sb_s(4, 5, 'ring start est='); a.inv(0x6e, sbj, [4, 2, 3]); log_sb(4)
    a.L('x'); a.raw(0x000e)
    code_pst = (8, 0, 5, a.done())
    a = A()                                              # static en(): v0..v7
    a.inv(0x71, getp, []); a.mro(0)
    a.cs(1, S('TBR0')); a.inv(0x72, mrem, [0, 1]); a.mro(4); a.iof(5, 4, g.T(LNG)); a.b21(0x38, 5, 'x')
    a.t21(0x1f, 4, g.T(LNG)); a.inv(0x6e, g.M(LNG, 'longValue', '()J'), [4]); a.mrw(4)
    a.inv(0x71, g.M('Ljava/lang/System;', 'currentTimeMillis', '()J'), []); a.mrw(2)
    a.raw(0xbc | 2 << 8 | 4 << 12)                                                   # dt = now - t0
    a.inv(0x71, g.M(LNG, 'valueOf', '(J)' + LNG), [2, 3]); a.mro(4); a.cs(1, S('TBRMS')); a.inv(0x72, mput, [0, 1, 4])
    a.cs(1, S('TBSPO')); a.inv(0x72, mget_, [0, 1]); a.mro(1); a.iof(5, 1, g.T(VIEW)); a.b21(0x38, 5, 'x')
    a.t21(0x1f, 1, g.T(VIEW))
    a.t21(0x22, 4, g.T(PRG)); a.c4(5, 2); a.raw(0x16 | 6 << 8, 0); a.inv(0x70, prinit, [4, 5, 6, 7])
    a.inv(0x6e, g.M(VIEW, 'post', '(Ljava/lang/Runnable;)Z'), [1, 4])
    sb_new(4); sb_s(4, 5, 'ring end ms='); a.inv(0x6e, sbj, [4, 2, 3]); log_sb(4)
    a.L('x'); a.raw(0x000e)
    code_pen = (8, 0, 5, a.done())
    g.cls(PRG, OBJ, 0x1, [('<init>', '(IJ)V', 0x10001, code_pri), ('st', '()V', 0x9, code_pst), ('en', '()V', 0x9, code_pen)],
          [('run', '()V', 0x1, code_prun)], [RUN], [('m', 'I'), ('t', 'J')])
    # ---- P283: burst watchdog. Twice a 50 MP burst got no frame at all (request sent, then silence; the camera stayed
    #      frozen until it was reopened). LTBWd.arm(n) at burst start posts a check 4 s later: if 'TBREM' still equals
    #      n (not one frame arrived), the first frames are sent again with the stored session / request / callback
    #      ('TBQ'); any exception (closed session ...) is logged, so the next log shows the cause. ----
    WD = 'LTBWd;'; fwn = g.Fd(WD, 'n', 'I')
    code_wdi = (2, 2, 1, [0x1070, oinit, 0, 0x0159, fwn, 0x000e])
    a = A()                                              # run(v9 this)
    a.L('t0')
    a.inv(0x71, getp, []); a.mro(0)
    a.cs(1, S('TBREM')); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [0, 1]); a.mro(2)
    a.iof(3, 2, tINT); a.b21(0x38, 3, 'ok')
    a.t21(0x1f, 2, tINT); a.inv(0x6e, ivl, [2]); a.mr(2); a.raw(0x52 | 3 << 8 | 9 << 12, fwn); a.b22(0x33, 2, 3, 'ok')
    a.cs(1, S('TBQ')); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [0, 1]); a.mro(4)
    sb_new(8); sb_s(8, 1, 'burst stalled: no frame in 4 s, n='); a.inv(0x6e, sbI, [8, 3]); log_sb(8)
    a.b21(0x38, 4, 'noq'); a.t21(0x1f, 4, tOA)
    a.c4(1, 0); a.raw(0x46 | 5 << 8, 4 | 1 << 8); a.t21(0x1f, 5, tSES)
    a.c4(1, 1); a.raw(0x46 | 6 << 8, 4 | 1 << 8); a.t21(0x1f, 6, tREQ)
    a.c4(1, 2); a.raw(0x46 | 7 << 8, 4 | 1 << 8); a.t21(0x1f, 7, tCB)
    a.inv(0x71, mainl, []); a.mro(1); a.t21(0x22, 8, tHND); a.inv(0x70, g.M(HND, '<init>', '(Landroid/os/Looper;)V'), [8, 1])
    a.c4(2, 0); a.c4(3, 4)
    a.L('lp'); a.inv(0x6e, cap, [5, 6, 7, 8]); a.raw(0xd8 | 2 << 8, 2 | 1 << 8); a.b22(0x34, 2, 3, 'lp')
    sb_new(8); sb_s(8, 1, 'burst stalled: resent 4 frames'); log_sb(8); a.go('ok')
    a.L('noq'); sb_new(8); sb_s(8, 1, 'burst stalled: no queue to resend'); log_sb(8)
    a.L('ok'); a.L('t1'); a.raw(0x000e)
    a.L('h'); a.raw(0x0d | 0 << 8); sb_new(8); sb_s(8, 1, 'burst stalled: resend failed '); a.inv(0x6e, sbo, [8, 0]); log_sb(8); a.raw(0x000e)
    w = a.done(); Lb = a.lab
    code_wdr = (10, 1, 5, w, [(Lb['t0'], Lb['t1'] - Lb['t0'], Lb['h'])])
    a = A()                                              # static arm(v4 n)
    a.t21(0x22, 0, g.T(WD)); a.inv(0x70, g.M(WD, '<init>', '(I)V'), [0, 4])
    a.inv(0x71, mainl, []); a.mro(1); a.t21(0x22, 2, tHND); a.inv(0x70, g.M(HND, '<init>', '(Landroid/os/Looper;)V'), [2, 1])
    a.raw(0x16 | 3 << 8, int(__import__('os').environ.get('WDMS', '2000'))); a.inv(0x6e, g.M(HND, 'postDelayed', '(' + RUN + 'J)Z'), [2, 0, 3, 4]); a.raw(0x000e)
    code_wda = (5, 1, 4, a.done())
    g.cls(WD, OBJ, 0x1, [('<init>', '(I)V', 0x10001, code_wdi), ('arm', '(I)V', 0x9, code_wda)],
          [('run', '()V', 0x1, code_wdr)], [RUN], [('n', 'I')])
    # ---- P280: LTBDF = GCam's file-name date format + '_XR' / '_ER' / '_SR' for 50 / 25 MP shots (tag set per shot,
    #      applied when the file's capture time is within 20 s of the tag) ----
    SDF = 'Ljava/text/SimpleDateFormat;'; SBF = 'Ljava/lang/StringBuffer;'
    code_dfi = (3, 3, 3, [0x3070, g.M(SDF, '<init>', '(' + STR + 'Ljava/util/Locale;)V'), 0x210, 0x000e])
    a = A()                                                    # static tag(v5 s)
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, S('TBTAG')); a.inv(0x72, mput, [0, 1, 5])
    a.inv(0x71, g.M('Ljava/lang/System;', 'currentTimeMillis', '()J'), []); a.mrw(2)
    a.inv(0x71, g.M(LNG, 'valueOf', '(J)' + LNG), [2, 3]); a.mro(2); a.cs(1, S('TBTAGT')); a.inv(0x72, mput, [0, 1, 2])
    sb_new(3); sb_s(3, 4, 'file tag '); a.inv(0x6e, sbs, [3, 5]); log_sb(3)
    a.raw(0x000e)
    code_dft = (6, 1, 3, a.done())
    a = A()                                                    # format(v8 this, v9 date, v10 sb, v11 fp)
    a.inv(0x6f, g.M(SDF, 'format', '(Ljava/util/Date;' + SBF + 'Ljava/text/FieldPosition;)' + SBF), [8, 9, 10, 11]); a.mro(0)
    a.inv(0x71, getp, []); a.mro(1); a.cs(2, S('TBTAG')); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [1, 2]); a.mro(6)
    a.b21(0x38, 6, 'r'); a.cs(2, S('TBTAGT')); a.inv(0x72, g.M('Ljava/util/Map;', 'get', '(' + OBJ + ')' + OBJ), [1, 2]); a.mro(2)
    a.b21(0x38, 2, 'r'); a.b21(0x38, 9, 'r')
    a.t21(0x1f, 2, g.T(LNG)); a.inv(0x6e, g.M(LNG, 'longValue', '()J'), [2]); a.mrw(2)
    a.inv(0x6e, g.M('Ljava/util/Date;', 'getTime', '()J'), [9]); a.mrw(4)
    a.raw(0xbc | 4 << 8 | 2 << 12)                                                           # sub-long/2addr v4, v2
    a.raw(0x16 | 2 << 8, 0); a.raw(0x31 | 7 << 8, 4 | 2 << 8); a.b21(0x3b, 7, 'pos'); a.raw(0x7d | 4 << 8 | 4 << 12)   # abs
    a.L('pos'); a.raw(0x17 | 2 << 8, 20000 & 0xffff, 20000 >> 16); a.raw(0x31 | 7 << 8, 4 | 2 << 8); a.b21(0x3c, 7, 'r')
    a.t21(0x1f, 6, g.T(STR)); a.cs(2, S('_'))
    # P283: '_TAG' goes before the last '_' segment (LMC's own suffix): ..._ER_J83 (appended after it, the _J83 was lost)
    sb_new(3); a.inv(0x6e, sbs, [3, 2]); a.inv(0x6e, sbs, [3, 6]); a.inv(0x6e, sbt, [3]); a.mro(6)
    a.inv(0x6e, g.M(SBF, 'lastIndexOf', '(' + STR + ')I'), [0, 2]); a.mr(2)
    a.c16(4, 9); a.b22(0x34, 2, 4, 'app')                                                    # no suffix after the date
    a.inv(0x6e, g.M(SBF, 'insert', '(I' + STR + ')' + SBF), [0, 2, 6]); a.go('r')
    a.L('app'); a.inv(0x6e, g.M(SBF, 'append', '(' + STR + ')' + SBF), [0, 6])
    a.L('r'); a.raw(0x11 | 0 << 8)
    code_dff = (12, 4, 4, a.done())
    g.cls('LTBDF;', SDF, 0x1, [('<init>', '(' + STR + 'Ljava/util/Locale;)V', 0x10001, code_dfi), ('tag', '(' + STR + ')V', 0x9, code_dft)],
          [('format', '(Ljava/util/Date;' + SBF + 'Ljava/text/FieldPosition;)' + SBF, 0x1, code_dff)])
    g.cls('LgetWidth;', OBJ, 0x1, [('<init>', '()V', 0x10001, code_pinit), ('rd', '(' + STR + ')' + STR, 0x2, code_rd),
          ('wr', '(' + STR + '[B)V', 0x2, code_wr), ('st', '(' + STR + ')' + STR, 0x2, code_st),
          ('inj', '(' + STR + STR + ')' + STR, 0x2, code_inj), ('unp', '(' + STR + STR + ')I', 0x2, code_unp)],
          [('compare', '(' + OBJ + OBJ + ')I', 0x1, code_cmp)], ['Ljava/util/Comparator;'])
    # ---- L.m(): "mem jused=MB jmax=MB native=MB <MemAvailable line>", never throws ----
    a = A()
    RT = 'Ljava/lang/Runtime;'
    a.t21(0x22, 4, tSB); a.inv(0x70, sbi, [4]); a.L('t0')
    a.inv(0x71, rtget, []); a.mro(5)
    a.inv(0x6e, g.M(RT, 'totalMemory', '()J'), [5]); a.mrw(0)
    a.inv(0x6e, g.M(RT, 'freeMemory', '()J'), [5]); a.mrw(2)
    a.raw(0x00bc | 0 << 8 | 2 << 12)                                   # sub-long/2addr v0, v2
    a.raw(0x0017 | 6 << 8, 0x0000, 0x0010)                            # const-wide/32 v6, 1048576
    a.raw(0x00be | 0 << 8 | 6 << 12)                                   # div-long/2addr v0, v6
    a.cs(8, S('mem jused=')); a.inv(0x6e, sbs, [4, 8]); a.inv(0x6e, sbj, [4, 0, 1])
    a.inv(0x6e, g.M(RT, 'maxMemory', '()J'), [5]); a.mrw(0); a.raw(0x00be | 0 << 8 | 6 << 12)
    a.cs(8, S(' jmax=')); a.inv(0x6e, sbs, [4, 8]); a.inv(0x6e, sbj, [4, 0, 1])
    a.inv(0x71, g.M('Landroid/os/Debug;', 'getNativeHeapAllocatedSize', '()J'), []); a.mrw(0); a.raw(0x00be | 0 << 8 | 6 << 12)
    a.cs(8, S(' native=')); a.inv(0x6e, sbs, [4, 8]); a.inv(0x6e, sbj, [4, 0, 1])
    FR = 'Ljava/io/FileReader;'; BR = 'Ljava/io/BufferedReader;'
    a.t21(0x22, 5, g.T(FR)); a.cs(8, S('/proc/meminfo')); a.inv(0x70, g.M(FR, '<init>', '(' + STR + ')V'), [5, 8])
    a.t21(0x22, 9, g.T(BR)); a.inv(0x70, g.M(BR, '<init>', '(Ljava/io/Reader;)V'), [9, 5])
    rl = g.M(BR, 'readLine', '()' + STR)
    a.inv(0x6e, rl, [9]); a.inv(0x6e, rl, [9]); a.inv(0x6e, rl, [9]); a.mro(8)
    a.inv(0x6e, g.M(BR, 'close', '()V'), [9])
    a.cs(5, S(' ')); a.inv(0x6e, sbs, [4, 5]); a.inv(0x6e, sbs, [4, 8])
    a.L('t1')
    a.L('h')
    a.inv(0x6e, sbt, [4]); a.mro(0); a.raw(0x0011)
    w = a.done()
    # handler: the string so far (v4 is set before the first instruction that can throw)
    code_m = (10, 0, 3, w, [(a.lab['t0'], a.lab['t1'] - a.lab['t0'], a.lab['h'])])
    g.cls(LCL, OBJ, 0x1, [('l', '(' + STR + ')V', 0x9, code_l), ('m', '()' + STR, 0x9, code_m)])
    # ---- U: default uncaught-exception handler: log "CRASH <thread> <stack> <mem>", then the previous handler ----
    UEH = 'Ljava/lang/Thread$UncaughtExceptionHandler;'; UCL = 'LTemporalBinning$U;'
    a = A(); a.L('t0')                                                 # regs 8: v0-v4 locals, v5 this, v6 thread, v7 throwable
    a.t21(0x22, 0, tSB); a.inv(0x70, sbi, [0])
    a.cs(1, S('CRASH thread=')); a.inv(0x6e, sbs, [0, 1]); a.inv(0x6e, sbo, [0, 6])
    a.cs(1, S(' ')); a.inv(0x6e, sbs, [0, 1]); a.inv(0x71, g.M(LCL, 'm', '()' + STR), []); a.mro(1); a.inv(0x6e, sbs, [0, 1])
    a.cs(1, S('\n')); a.inv(0x6e, sbs, [0, 1])
    a.inv(0x71, g.M('Landroid/util/Log;', 'getStackTraceString', '(Ljava/lang/Throwable;)' + STR), [7]); a.mro(1)
    a.inv(0x6e, sbs, [0, 1]); a.inv(0x6e, sbt, [0]); a.mro(0); a.inv(0x71, ll, [0])
    a.L('t1')
    a.L('h')
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, S('TBUEH')); a.inv(0x72, mget, [0, 1]); a.mro(0)
    a.iof(1, 0, g.T(UEH)); a.b21(0x38, 1, 'ret')
    a.t21(0x1f, 0, g.T(UEH)); a.inv(0x72, g.M(UEH, 'uncaughtException', '(Ljava/lang/Thread;Ljava/lang/Throwable;)V'), [0, 6, 7])
    a.L('ret'); a.raw(0x000e)
    w = a.done()
    code_u = (8, 3, 3, w, [(a.lab['t0'], a.lab['t1'] - a.lab['t0'], a.lab['h'])])
    code_uinit = (1, 1, 1, [0x1070, oinit, 0, 0x000e])
    g.cls(UCL, OBJ, 0x1, [('<init>', '()V', 0x10001, code_uinit)],
          [('uncaughtException', '(Ljava/lang/Thread;Ljava/lang/Throwable;)V', 0x1, code_u)], [UEH])
    # ---- Motion long-press: shutter / ISO pickers (Laction; is created by LDR.init via Class.forName("action")) ----
    VLC = 'Landroid/view/View$OnLongClickListener;'; DCL = 'Landroid/content/DialogInterface$OnClickListener;'
    DI = 'Landroid/content/DialogInterface;'; ADB = 'Landroid/app/AlertDialog$Builder;'; CTX = 'Landroid/content/Context;'
    CS = 'Ljava/lang/CharSequence;'; ACL = 'Laction;'; ICL = 'Laction$I;'
    showm = g.M(ACL, 'd', '(' + CTX + CS + '[' + CS + 'I' + DCL + ')V')
    a = A()                                                    # d(ctx v1, title v2, items v3, checked v4, listener v5)
    a.t21(0x22, 0, g.T(ADB)); a.inv(0x70, g.M(ADB, '<init>', '(' + CTX + ')V'), [0, 1])
    a.inv(0x6e, g.M(ADB, 'setTitle', '(' + CS + ')' + ADB), [0, 2])
    a.inv(0x6e, g.M(ADB, 'setSingleChoiceItems', '([' + CS + 'I' + DCL + ')' + ADB), [0, 3, 4, 5])
    a.inv(0x6e, g.M(ADB, 'show', '()Landroid/app/AlertDialog;'), [0]); a.raw(0x000e)
    code_d = (6, 5, 5, a.done())
    def items(r, t, labels):                                   # v r = new CharSequence[n] with the labels (t, t+1 temps)
        a.c16(t, len(labels)); a.raw(0x23 | r << 8 | t << 12, g.T('[' + CS))
        for i, l in enumerate(labels):
            a.cs(t, S(l)); a.c16(t + 1, i); a.raw(0x4d | t << 8, r | (t + 1) << 8)
    SSL = ['Auto', '1/2000', '1/1000', '1/500', '1/250', '1/125', '1/60', '1/30', '1/15', '1/8', '1/4', '1/2', '1 s', '2 s', '3 s']
    ISL = ['Auto', 'ISO 50', 'ISO 100', 'ISO 200', 'ISO 400', 'ISO 800', 'ISO 1600', 'ISO 3200', 'ISO 6400']
    SETV = g.M('LMC/pref;', 'setValue', '(' + STR + 'I)V')
    VW = 'Landroid/view/View;'; VG = 'Landroid/view/ViewGroup;'; LLY = 'Landroid/widget/LinearLayout;'
    NP = 'Landroid/widget/NumberPicker;'; NPL = 'Landroid/widget/NumberPicker$OnValueChangeListener;'
    FLP = 'Landroid/widget/FrameLayout$LayoutParams;'; VGLP = 'Landroid/view/ViewGroup$LayoutParams;'
    LLP = 'Landroid/widget/LinearLayout$LayoutParams;'; MLP = 'Landroid/view/ViewGroup$MarginLayoutParams;'
    TV = 'Landroid/widget/TextView;'; GD = 'Landroid/graphics/drawable/GradientDrawable;'; DR = 'Landroid/graphics/drawable/Drawable;'
    DM = 'Landroid/util/DisplayMetrics;'; RES = 'Landroid/content/res/Resources;'
    fb = lambda f: struct.unpack('<I', struct.pack('<f', f))[0]
    a = A()                                                    # equals(Object): LDR button -> remember it, post run(); v0.. , v3 this, v4 arg
    a.iof(0, 4, g.T(VW)); a.b21(0x38, 0, 'eqr')
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, S('TBLDR')); a.inv(0x72, mput, [0, 1, 4])
    a.t21(0x1f, 4, g.T(VW)); a.inv(0x6e, g.M(VW, 'post', '(' + RUN + ')Z'), [4, 3])
    a.L('eqr'); a.c4(0, 0); a.raw(0x000f)
    code_eq = (5, 2, 3, a.done())
    # run(): panel sync. Motion on -> panel (built once per window) visible; off -> gone. v15 this
    a = A()
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, S('TBLDR')); a.inv(0x72, mget, [0, 1]); a.mro(2)
    a.iof(5, 2, g.T(VW)); a.b21(0x38, 5, 'rret'); a.t21(0x1f, 2, g.T(VW))
    a.cs(3, S('pref_enable_ldr_key')); a.inv(0x71, MS, [3]); a.mr(3)
    a.cs(1, S('TBPANEL')); a.inv(0x72, mget, [0, 1]); a.mro(4)
    a.iof(5, 4, g.T(VW)); a.b21(0x38, 5, 'rnew'); a.t21(0x1f, 4, g.T(VW))
    a.inv(0x6e, g.M(VW, 'isAttachedToWindow', '()Z'), [4]); a.mr(5); a.b21(0x38, 5, 'rnew')
    a.c16(5, 8); a.b21(0x38, 3, 'rvis'); a.c4(5, 0)
    a.L('rvis'); a.inv(0x6e, g.M(VW, 'setVisibility', '(I)V'), [4, 5]); a.go('rret')
    a.L('rnew'); a.b21(0x38, 3, 'rret')
    a.inv(0x6e, g.M(VW, 'getContext', '()' + CTX), [2]); a.mro(6)
    a.inv(0x6e, g.M(VW, 'getRootView', '()' + VW), [2]); a.mro(7)
    a.iof(5, 7, g.T(VG)); a.b21(0x38, 5, 'rret'); a.t21(0x1f, 7, g.T(VG))
    a.inv(0x6e, g.M(CTX, 'getResources', '()' + RES), [6]); a.mro(5)
    a.inv(0x6e, g.M(RES, 'getDisplayMetrics', '()' + DM), [5]); a.mro(5)
    a.raw(0x52 | 8 << 8 | 5 << 12, g.Fd(DM, 'density', 'F'))                  # v8 = density
    a.raw(0x52 | 5 << 8 | 5 << 12, g.Fd(DM, 'heightPixels', 'I'))             # v5 = screen height px
    def px(t, dp, toint=True):
        a.c32(t, fb(dp)); a.raw(0xc8 | t << 8 | 8 << 12)
        if toint: a.raw(0x87 | t << 8 | t << 12)
    # container: full screen, three rulers stacked at the left (layout of the reference port, 1171 px wide units)
    FL = 'Landroid/widget/FrameLayout;'; RL = 'Lruler;'
    a.inv(0x6e, g.M(CTX, 'getResources', '()' + RES), [6]); a.mro(5)
    a.inv(0x6e, g.M(RES, 'getDisplayMetrics', '()' + DM), [5]); a.mro(5)
    a.raw(0x52 | 8 << 8 | 5 << 12, g.Fd(DM, 'widthPixels', 'I')); a.raw(0x82 | 8 << 8 | 8 << 12)
    a.c32(5, fb(1171.0)); a.raw(0xc9 | 8 << 8 | 5 << 12)                       # v8 = unit
    a.t21(0x22, 4, g.T(FL)); a.inv(0x70, g.M(FL, '<init>', '(' + CTX + ')V'), [4, 6])
    def ruler(key, labels, top):
        a.t21(0x22, 9, g.T(RL)); a.cs(10, S(key))
        a.c16(13, len(labels)); a.raw(0x23 | 11 << 8 | 13 << 12, g.T('[' + STR))
        for i, l in enumerate(labels):
            a.cs(13, S(l)); a.c16(14, i); a.raw(0x4d | 13 << 8, 11 | 14 << 8)
        a.raw(0x01 | 12 << 8 | 8 << 12)
        a.inv(0x70, g.M(RL, '<init>', '(' + CTX + STR + '[' + STR + 'F)V'), [9, 6, 10, 11, 12])
        a.t21(0x22, 11, g.T(FLP)); px(12, 250); px(13, 272); a.c16(14, 51)
        a.inv(0x70, g.M(FLP, '<init>', '(III)V'), [11, 12, 13, 14])
        px(12, top - 40); a.c4(13, 0); a.inv(0x6e, g.M(MLP, 'setMargins', '(IIII)V'), [11, 13, 12, 13, 13])
        a.inv(0x6e, g.M(VG, 'addView', '(' + VW + VGLP + ')V'), [4, 9, 11])
    ruler('pref_motion_ss_key', ['Auto'] + [x if ' ' in x else x + 's' for x in SSL[1:]], 548)
    ruler('pref_motion_iso_key', ['Auto'] + [x[4:] for x in ISL[1:]], 952)
    ruler('pref_motion_af_key', ['Auto'] + FOCUS_L[1:], 1428)
    a.t21(0x22, 11, g.T(FLP)); a.c4(12, -1); a.c4(13, -1); a.c16(14, 51)
    a.inv(0x70, g.M(FLP, '<init>', '(III)V'), [11, 12, 13, 14])
    a.inv(0x6e, g.M(VG, 'addView', '(' + VW + VGLP + ')V'), [7, 4, 11])
    a.cs(1, S('TBPANEL')); a.inv(0x72, mput, [0, 1, 4])
    a.L('rret'); a.raw(0x000e)
    code_run = (16, 1, 5, a.done())
    # put(Pair[] noise profile, ljm result) <- GCam ohv.k: on quad (RES, props 'quadTo') captures scale S, O
    PR = 'Landroid/util/Pair;'; DBL = 'Ljava/lang/Double;'
    NZS = float(__import__('os').environ.get('NZS', '0.13')); NZO = float(__import__('os').environ.get('NZO', '0.065'))
    db = lambda f: struct.unpack('<4H', struct.pack('<d', f))
    a = A()                                                    # v11 this, v12 profile, v13 result
    a.iof(0, 12, g.T('[' + PR)); a.b21(0x38, 0, 'nzr')
    a.inv(0x71, getp, []); a.mro(0); a.cs(1, QKEY); a.inv(0x72, mget, [0, 1]); a.mro(1); a.b21(0x38, 1, 'nzr')
    a.cs(1, S('TB25')); a.inv(0x72, mget, [0, 1]); a.mro(13)                                 # P271: 25 MP flag
    a.cs(1, S('nightS')); a.inv(0x72, mget, [0, 1]); a.mro(1); a.b21(0x38, 1, 'nzs1')      # P261: v0:v1 = night scale s
    a.t21(0x1f, 1, tINT); a.inv(0x6e, ivl, [1]); a.mr(1); a.raw(0x83 | 6 << 8 | 1 << 12)       # v6:v7 = (double) s256
    a.raw(0x18 | 8 << 8, *db(1.0 / 256)); a.raw(0xcd | 6 << 8 | 8 << 12); a.raw(0x04 | 0 << 8 | 6 << 12); a.go('nzs2')
    a.L('nzs1'); a.raw(0x18 | 0 << 8, *db(1.0)); a.L('nzs2')
    a.b21(0x38, 13, 'nzb0'); a.raw(0x18 | 8 << 8, *db(0.5)); a.raw(0xcd | 0 << 8 | 8 << 12); a.L('nzb0')   # s x 0.5
    a.t21(0x1f, 12, g.T('[' + PR)); a.raw(0x21 | 2 << 8 | 12 << 12)
    a.raw(0x23 | 3 << 8 | 2 << 12, g.T('[' + PR)); a.c4(4, 0)
    FFI = g.Fd(PR, 'first', OBJ); FSE = g.Fd(PR, 'second', OBJ)
    dv = g.M(DBL, 'doubleValue', '()D'); dvo = g.M(DBL, 'valueOf', '(D)' + DBL)
    a.L('nzl'); a.b22(0x35, 4, 2, 'nzd')
    a.raw(0x46 | 5 << 8, 12 | 4 << 8); a.b21(0x38, 5, 'nzn')
    a.raw(0x54 | 6 << 8 | 5 << 12, FFI); a.t21(0x1f, 6, g.T(DBL)); a.inv(0x6e, dv, [6]); a.raw(0x0b | 6 << 8)
    a.raw(0x18 | 8 << 8, *db(NZS)); a.raw(0xcd | 6 << 8 | 8 << 12); a.raw(0xcd | 6 << 8 | 0 << 12); a.inv(0x71, dvo, [6, 7]); a.mro(10)
    a.raw(0x54 | 6 << 8 | 5 << 12, FSE); a.t21(0x1f, 6, g.T(DBL)); a.inv(0x6e, dv, [6]); a.raw(0x0b | 6 << 8)
    a.raw(0x18 | 8 << 8, *db(NZO)); a.raw(0xcd | 6 << 8 | 8 << 12); a.raw(0xcd | 6 << 8 | 0 << 12); a.raw(0xcd | 6 << 8 | 0 << 12)
    a.b21(0x38, 13, 'nzb1'); a.raw(0x18 | 8 << 8, *db(2.0)); a.raw(0xcd | 6 << 8 | 8 << 12); a.L('nzb1')   # O: s^2 x 0.5
    a.inv(0x71, dvo, [6, 7]); a.mro(6)
    a.t21(0x22, 5, g.T(PR)); a.inv(0x70, g.M(PR, '<init>', '(' + OBJ + OBJ + ')V'), [5, 10, 6])
    a.raw(0x4d | 5 << 8, 3 | 4 << 8)
    a.L('nzn'); a.raw(0xd8 | 4 << 8, 4 | 1 << 8); a.go('nzl')
    a.L('nzd'); a.cs(1, S('noise model scaled for 50 MP S x%g O x%g' % (NZS, NZO))); a.inv(0x71, ll, [1]); a.raw(0x11 | 3 << 8)
    a.L('nzr'); a.raw(0x11 | 12 << 8)
    code_put = (14, 3, 3, a.done())
    a = A()                                                    # onLongClick: unused now (kept for the interface)
    a.c4(0, 0); a.raw(0x000f)
    code_lc = (3, 2, 0, a.done())
    a = A()                                                    # wheel moved: pref (picker tag) = new value; v2 this, v3 picker, v4 old, v5 new
    a.inv(0x6e, g.M(VW, 'getTag', '()' + OBJ), [3]); a.mro(0)
    a.iof(1, 0, tSTR); a.b21(0x38, 1, 'nvr'); a.t21(0x1f, 0, tSTR)
    a.inv(0x71, SETV, [0, 5])
    a.L('nvr'); a.raw(0x000e)
    code_nv = (6, 4, 2, a.done())
    a = A()                                                    # onClick (shutter): v0-v4, v5 this, v6 dialog, v7 which
    a.cs(0, S('pref_motion_ss_key')); a.inv(0x71, SETV, [0, 7])
    a.inv(0x72, g.M(DI, 'dismiss', '()V'), [6])
    a.t21(0x1f, 6, g.T('Landroid/app/Dialog;')); a.inv(0x6e, g.M('Landroid/app/Dialog;', 'getContext', '()' + CTX), [6]); a.mro(0)
    items(1, 2, ISL)
    a.cs(2, S('ISO (50 MP, Motion on)')); a.cs(3, S('pref_motion_iso_key')); a.inv(0x71, MS, [3]); a.mr(3)
    a.t21(0x22, 4, g.T(ICL)); a.inv(0x70, g.M(ICL, '<init>', '()V'), [4])
    a.inv(0x71, showm, [0, 2, 1, 3, 4]); a.raw(0x000e)
    code_oc = (8, 3, 5, a.done())
    g.cls(ACL, OBJ, 0x1, [('<init>', '()V', 0x10001, (1, 1, 1, [0x1070, oinit, 0, 0x000e])), ('d', '(' + CTX + CS + '[' + CS + 'I' + DCL + ')V', 0x9, code_d)],
          [('onLongClick', '(Landroid/view/View;)Z', 0x1, code_lc), ('onClick', '(' + DI + 'I)V', 0x1, code_oc),
           ('onValueChange', '(' + NP + 'II)V', 0x1, code_nv), ('equals', '(' + OBJ + ')Z', 0x1, code_eq),
           ('run', '()V', 0x1, code_run), ('put', '(' + OBJ + OBJ + ')' + OBJ, 0x1, code_put)],
          [VLC, DCL, NPL, RUN, 'Ljava/util/Map;'])
    a = A()                                                    # ISO onClick: v0, v1 this, v2 dialog, v3 which
    a.cs(0, S('pref_motion_iso_key')); a.inv(0x71, SETV, [0, 3])
    a.inv(0x72, g.M(DI, 'dismiss', '()V'), [2]); a.raw(0x000e)
    code_ic = (4, 3, 2, a.done())
    g.cls(ICL, OBJ, 0x1, [('<init>', '()V', 0x10001, (1, 1, 1, [0x1070, oinit, 0, 0x000e]))],
          [('onClick', '(' + DI + 'I)V', 0x1, code_ic)], [DCL])
    # ---- Lruler: vertical scale (text + ticks, the selected value on the marker line); drag to scroll ----
    RL = 'Lruler;'; PNT = 'Landroid/graphics/Paint;'; CNV = 'Landroid/graphics/Canvas;'; ME = 'Landroid/view/MotionEvent;'
    VW = 'Landroid/view/View;'; fb = lambda f: struct.unpack('<I', struct.pack('<f', f))[0]
    fK = g.Fd(RL, 'k', STR); fL = g.Fd(RL, 'l', '[' + STR); fV = g.Fd(RL, 'v', 'F'); fY = g.Fd(RL, 'y', 'F')
    fP = g.Fd(RL, 'p', PNT); fA = g.Fd(RL, 'a', 'I'); fS = g.Fd(RL, 's', 'F'); fD = g.Fd(RL, 'd', 'F')
    IG = lambda d_, o_, f_: a.raw(0x52 | d_ << 8 | o_ << 12, f_); IP = lambda v_, o_, f_: a.raw(0x59 | v_ << 8 | o_ << 12, f_)
    IGO = lambda d_, o_, f_: a.raw(0x54 | d_ << 8 | o_ << 12, f_); IPO = lambda v_, o_, f_: a.raw(0x5b | v_ << 8 | o_ << 12, f_)
    MV = lambda d_, s_: a.raw(0x02 | d_ << 8, s_); MVO = lambda d_, s_: a.raw(0x08 | d_ << 8, s_)
    F3 = lambda op, d_, x_, y_: a.raw(op | d_ << 8, x_ | y_ << 8)          # 23x: add 0xa6 sub 0xa7 mul 0xa8
    F2 = lambda op, d_, x_: a.raw(op | d_ << 8 | x_ << 12)                 # 2addr: add 0xc6 sub 0xc7 mul 0xc8 div 0xc9
    a = A()                       # <init>(ctx, key, labels, density): v4 this, v5 ctx, v6 key, v7 labels, v8 density
    a.inv(0x70, g.M(VW, '<init>', '(' + CTX + ')V'), [4, 5])
    IPO(6, 4, fK); IPO(7, 4, fL); IP(8, 4, fD)
    a.inv(0x71, MS, [6]); a.mr(0); a.raw(0x21 | 1 << 8 | 7 << 12)
    a.b22(0x34, 0, 1, 'ci1'); a.c4(0, 0); a.L('ci1'); a.b21(0x3b, 0, 'ci2'); a.c4(0, 0); a.L('ci2')
    a.raw(0x82 | 0 << 8 | 0 << 12); IP(0, 4, fV)
    a.c32(2, fb(32.5)); F2(0xc8, 2, 8); IP(2, 4, fS)
    a.t21(0x22, 1, g.T(PNT)); a.c4(2, 1); a.inv(0x70, g.M(PNT, '<init>', '(I)V'), [1, 2])
    a.c4(2, -1); a.inv(0x6e, g.M(PNT, 'setColor', '(I)V'), [1, 2])
    a.c32(2, fb(28.0)); F2(0xc8, 2, 8); a.inv(0x6e, g.M(PNT, 'setTextSize', '(F)V'), [1, 2])
    a.raw(0x62 | 2 << 8, g.Fd('Landroid/graphics/Paint$Align;', 'RIGHT', 'Landroid/graphics/Paint$Align;'))
    a.inv(0x6e, g.M(PNT, 'setTextAlign', '(Landroid/graphics/Paint$Align;)V'), [1, 2])
    a.c32(2, fb(2.0)); F2(0xc8, 2, 8); a.c4(0, 0); a.c4(3, 0)
    a.c32(5, 0x70000000); a.inv(0x6e, g.M(PNT, 'setShadowLayer', '(FFFI)V'), [1, 2, 0, 3, 5])
    IPO(1, 4, fP); a.raw(0x000e)
    code_ri = (9, 5, 5, a.done())
    a = A()                       # onDraw(canvas): this v24 -> v14, canvas v25 -> v15; range args v16..v21
    MVO(14, 24); MVO(15, 25)
    IGO(0, 14, fP); IGO(1, 14, fL); a.raw(0x21 | 2 << 8 | 1 << 12)
    IG(3, 14, fV); IG(4, 14, fS); IG(5, 14, fD)
    a.inv(0x6e, g.M(VW, 'getWidth', '()I'), [14]); a.mr(6); a.raw(0x82 | 6 << 8 | 6 << 12)
    a.c32(7, fb(40.0)); F2(0xc8, 7, 5)                                        # marker y
    MVO(16, 15); MVO(21, 0)
    a.c32(9, fb(8.0)); F2(0xc8, 9, 5); a.inv(0x6e, g.M(PNT, 'setStrokeWidth', '(F)V'), [0, 9])
    a.c16(9, 255); a.inv(0x6e, g.M(PNT, 'setAlpha', '(I)V'), [0, 9])
    a.c32(9, fb(137.0)); F3(0xa8, 17, 9, 5)
    a.c32(9, fb(234.0)); F3(0xa8, 19, 9, 5)
    MV(18, 7); MV(20, 7)
    DL = g.M(CNV, 'drawLine', '(FFFF' + PNT + ')V'); DT = g.M(CNV, 'drawText', '(' + STR + 'FF' + PNT + ')V')
    a.invr(0x74, DL, 16, 6)
    a.c32(9, fb(2.0)); F2(0xc8, 9, 5); a.inv(0x6e, g.M(PNT, 'setStrokeWidth', '(F)V'), [0, 9])
    a.c32(9, fb(137.0)); F3(0xa8, 22, 9, 5)                                   # tick x0
    a.c32(9, fb(215.0)); F3(0xa8, 23, 9, 5)                                   # tick x1
    a.inv(0x6e, g.M(VW, 'getHeight', '()I'), [14]); a.mr(13); a.raw(0x82 | 13 << 8 | 13 << 12)
    a.c4(8, 0)
    a.L('dl'); a.b22(0x35, 8, 2, 'dend')
    a.raw(0x82 | 9 << 8 | 8 << 12); F2(0xc7, 9, 3)                           # v9 = i - v
    a.raw(0x01 | 10 << 8 | 9 << 12); F2(0xc8, 10, 4); F2(0xc6, 10, 7)         # v10 = y
    a.c4(11, 0); F3(0x2d, 12, 10, 11); a.b21(0x3a, 12, 'dnx')
    F3(0x2e, 12, 10, 13); a.b21(0x3c, 12, 'dnx')
    F3(0x2d, 12, 9, 11); a.b21(0x3b, 12, 'dab'); a.raw(0x7f | 9 << 8 | 9 << 12)
    a.L('dab')
    IG(11, 14, fA); a.c32(12, fb(32.0)); a.b21(0x38, 11, 'dal'); a.c32(12, fb(24.0))
    a.L('dal'); F2(0xc8, 9, 12); a.c32(12, fb(255.0)); F2(0xc7, 12, 9)
    a.raw(0x87 | 12 << 8 | 12 << 12); a.c16(11, 35); a.b22(0x35, 12, 11, 'dal2'); a.raw(0x01 | 12 << 8 | 11 << 12)
    a.L('dal2'); a.inv(0x6e, g.M(PNT, 'setAlpha', '(I)V'), [0, 12])
    MV(17, 22); MV(18, 10); MV(19, 23); MV(20, 10); a.invr(0x74, DL, 16, 6)
    a.raw(0x46 | 11 << 8, 1 | 8 << 8); MVO(17, 11)
    a.c32(9, fb(113.0)); F3(0xa8, 18, 9, 5)
    a.c32(9, fb(10.0)); F2(0xc8, 9, 5); F3(0xa6, 19, 10, 9)
    MVO(20, 0); a.invr(0x74, DT, 16, 5)
    a.L('dnx'); a.raw(0xd8 | 8 << 8, 8 | 1 << 8); a.go('dl')
    a.L('dend'); a.raw(0x000e)
    code_rd = (26, 2, 6, a.done())
    a = A()                       # onTouchEvent(e): v6 this, v7 e
    a.inv(0x6e, g.M(ME, 'getActionMasked', '()I'), [7]); a.mr(0)
    a.inv(0x6e, g.M(ME, 'getY', '()F'), [7]); a.mr(1)
    a.b21(0x39, 0, 'tmv')
    IP(1, 6, fY); a.c4(2, 1); IP(2, 6, fA)
    a.inv(0x6e, g.M(VW, 'getParent', '()Landroid/view/ViewParent;'), [6]); a.mro(2); a.b21(0x38, 2, 'tdn')
    a.c4(3, 1); a.inv(0x72, g.M('Landroid/view/ViewParent;', 'requestDisallowInterceptTouchEvent', '(Z)V'), [2, 3])
    a.L('tdn'); a.inv(0x6e, g.M(VW, 'invalidate', '()V'), [6]); a.go('tret')
    a.L('tmv'); a.c4(2, 2); a.b22(0x33, 0, 2, 'tup')
    IG(2, 6, fY); F3(0xa7, 3, 2, 1); IG(4, 6, fS); F2(0xc9, 3, 4); IG(4, 6, fV)
    a.c32(5, fb(0.5)); F2(0xc6, 5, 4); a.raw(0x87 | 5 << 8 | 5 << 12)          # old step
    F2(0xc6, 4, 3)
    a.c4(2, 0); F3(0x2d, 3, 4, 2); a.b21(0x3b, 3, 'tk1'); a.c4(4, 0)
    a.L('tk1'); IGO(2, 6, fL); a.raw(0x21 | 2 << 8 | 2 << 12); a.raw(0xd8 | 2 << 8, 2 | 0xff << 8); a.raw(0x82 | 2 << 8 | 2 << 12)
    F3(0x2e, 3, 4, 2); a.b21(0x3d, 3, 'tk2'); a.raw(0x01 | 4 << 8 | 2 << 12)
    a.L('tk2'); IP(4, 6, fV); IP(1, 6, fY)
    a.c32(3, fb(0.5)); F2(0xc6, 3, 4); a.raw(0x87 | 3 << 8 | 3 << 12); a.b22(0x32, 3, 5, 'tnh')
    a.c4(2, 4); a.inv(0x6e, g.M(VW, 'performHapticFeedback', '(I)Z'), [6, 2])
    a.L('tnh'); a.inv(0x6e, g.M(VW, 'invalidate', '()V'), [6]); a.go('tret')
    a.L('tup'); a.c4(2, 1); a.b22(0x32, 0, 2, 'tend'); a.c4(2, 3); a.b22(0x33, 0, 2, 'tret')
    a.L('tend'); IG(4, 6, fV); a.c32(3, fb(0.5)); F2(0xc6, 3, 4); a.raw(0x87 | 3 << 8 | 3 << 12)
    a.raw(0x82 | 4 << 8 | 3 << 12); IP(4, 6, fV); a.c4(2, 0); IP(2, 6, fA)
    IGO(2, 6, fK); a.inv(0x71, SETV, [2, 3]); a.inv(0x6e, g.M(VW, 'invalidate', '()V'), [6])
    a.L('tret'); a.c4(0, 1); a.raw(0x000f)
    code_rt = (8, 2, 2, a.done())
    g.cls(RL, VW, 0x1, [('<init>', '(' + CTX + STR + '[' + STR + 'F)V', 0x10001, code_ri)],
          [('onDraw', '(' + CNV + ')V', 0x4, code_rd), ('onTouchEvent', '(' + ME + ')Z', 0x1, code_rt)],
          [], [('k', STR), ('l', '[' + STR), ('v', 'F'), ('y', 'F'), ('p', PNT), ('a', 'I'), ('s', 'F'), ('d', 'F')])
    return g.build()


if __name__ == '__main__':
    import sys
    b = build_classes3(); open(sys.argv[1], 'wb').write(b); print(len(b), 'bytes')
