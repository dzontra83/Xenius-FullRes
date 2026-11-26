#!/usr/bin/env python3
"""XENIUS P163 — HDR+ frame count in the photo's EXIF Model, on top of P162B (classes2.dex unchanged).

Gallery "camera" line becomes e.g.  Google V2547A 13/15 frames  (merged / handed to HDR+).
 E1 Lohv.q (StaticMetadata for both GCam engines): Model = Build.MODEL + " " + 18-char placeholder
    ("RAW50_REQRAW50_REQ"). libgcam writes it into the JPEG EXIF.
 E2 Lohy.accept (ShotLogData callback, the existing merge-summary hook):
    pc 0  : remember the shot id   -> props["ShotLogData_merge_process_time_get"] = id
    pc 366: store "<id>:<merged>/<original>" -> props["ShotLogData_original_payload_frame_count_get"]
 E3 Loho.onDataAvailable (final encoded JPEG, copied into a Java ByteBuffer) rewritten with 16 registers:
    after the copy, inside a catch-all try, every placeholder in the first 64 KB is overwritten in place with
    "<merged>/<original> frames" padded to 18 chars, if the stored id matches this shot; else "/ frames"
    (= stats not ready yet). Same length -> no EXIF offsets change. Then the original callback runs.

Run: python3 build_p163.py XENIUS_P162B_GYRO_UNSIGNED.apk XENIUS_P163_EXIFCOUNT_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr

P162B_DEX = 'ac8fdc076487dd291cdad201ad4fbaf538350f79930cdfa6fa8127832e0a8714'
PH = 18


class S:
    """small assembler with label fix-ups (21t, 22t, 30t)."""
    def __init__(self, base=0): self.base = base; self.w = []; self.fix = []; self.lab = {}
    def pc(self): return self.base + len(self.w)
    def L(self, n): self.lab[n] = self.pc()
    def raw(self, *x): self.w += list(x)
    def inv(self, op, m, regs):
        assert len(regs) <= 5 and all(r < 16 for r in regs)
        g = regs[4] if len(regs) == 5 else 0; p = 0
        for i, r in enumerate(regs[:4]): p |= r << (4 * i)
        self.w += [op | len(regs) << 12 | g << 8, m, p]
    def mr(self, a): self.w += [0x0a | a << 8]
    def mro(self, a): self.w += [0x0c | a << 8]
    def cs(self, a, s): assert s < 65536; self.w += [0x1a | a << 8, s]
    def c4(self, a, v): self.w += [0x12 | a << 8 | (v & 15) << 12]
    def c16(self, a, v): self.w += [0x13 | a << 8, v & 0xffff]
    def c32(self, a, v): self.w += [0x14 | a << 8, v & 0xffff, (v >> 16) & 0xffff]
    def lit8(self, op, a, b, v): self.w += [op | a << 8, b | (v & 0xff) << 8]
    def b21(self, op, a, t): self.fix.append((len(self.w), self.pc(), t, 1)); self.w += [op | a << 8, 0]
    def b22(self, op, a, b, t): self.fix.append((len(self.w), self.pc(), t, 1)); self.w += [op | a << 8 | b << 12, 0]
    def go(self, t): self.fix.append((len(self.w), self.pc(), t, 2)); self.w += [0x2a, 0, 0]
    def done(self):
        for i, src, t, k in self.fix:
            off = (self.lab[t] if isinstance(t, str) else t) - src
            self.w[i + 1] = off & 0xffff
            if k == 2: self.w[i + 2] = (off >> 16) & 0xffff
            else: assert -32768 <= off < 32768
        return self.w


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P162B_DEX, 'classes.dex is not P162B'
    open('/tmp/_p163.dex', 'wb').write(raw); d = Dex('/tmp/_p163.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    T = lambda t: d.types.index(t)
    STR = 'Ljava/lang/String;'; BB = 'Ljava/nio/ByteBuffer;'
    cat = M(STR, 'concat', '(Ljava/lang/String;)Ljava/lang/String;')
    vo = M(STR, 'valueOf', '(Ljava/lang/Object;)Ljava/lang/String;')
    vi = M(STR, 'valueOf', '(I)Ljava/lang/String;')
    sw = M(STR, 'startsWith', '(Ljava/lang/String;)Z')
    ln = M(STR, 'length', '()I')
    sub1 = M(STR, 'substring', '(I)Ljava/lang/String;')
    sub2 = M(STR, 'substring', '(II)Ljava/lang/String;')
    gb = M(STR, 'getBytes', '()[B')
    props = M('Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    get = M('Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    put = M('Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    bget = M(BB, 'get', '(I)B'); bput = M(BB, 'put', '(IB)Ljava/nio/ByteBuffer;'); blim = M(BB, 'limit', '()I')
    SP, PHS, COL, SL, FR = sid(d, ' '), sid(d, 'RAW50_REQ'), sid(d, ':'), sid(d, '/'), sid(d, ' frames')
    KID, KVAL = sid(d, 'ShotLogData_merge_process_time_get'), sid(d, 'ShotLogData_original_payload_frame_count_get')
    out = {}

    # ---- E1 Lohv.q: model placeholder ----
    m = one(d, 'Lohv;', 'q'); c = Code(raw, d.code[m])
    assert c.w[24:26] == [0x0062, [i for i, f in enumerate(d.fields) if f == ('Landroid/os/Build;', STR, 'MODEL')][0]]
    assert c.w[26] & 0xff == 0x53                                         # iget-wide v2,v3 overwrites v2 next
    def E1(p, na):
        a = S(p); a.cs(2, SP); a.inv(0x6e, cat, [0, 2]); a.mro(0)
        a.cs(2, PHS); a.inv(0x6e, cat, [0, 2]); a.mro(0); a.inv(0x6e, cat, [0, 2]); a.mro(0)
        return a.done()
    insert(c, 26, E1); check(c); out[m] = c.build()

    # ---- E2 Lohy.accept ----
    m = one(d, 'Lohy;', 'accept'); c = Code(raw, d.code[m])
    assert c.regs == 11 and c.ins == 4 and c.w[366:368] == [0x041a, PHS], [hex(x) for x in c.w[366:368]]
    nzk = lambda n: [i for i, f in enumerate(d.fields) if f == ('Lnzk;', 'I', n)][0]
    def E2b(p, na):   # v3 = Lnzk; v0,v4,v5,v6 free
        a = S(p)
        a.inv(0x71, props, []); a.mro(0)
        a.cs(6, KID); a.inv(0x72, get, [0, 6]); a.mro(4); a.inv(0x71, vo, [4]); a.mro(4)
        a.cs(6, COL); a.inv(0x6e, cat, [4, 6]); a.mro(4)
        a.raw(0x0052 | 5 << 8 | 3 << 12, nzk('o')); a.inv(0x71, vi, [5]); a.mro(5)        # merged
        a.inv(0x6e, cat, [4, 5]); a.mro(4); a.cs(6, SL); a.inv(0x6e, cat, [4, 6]); a.mro(4)
        a.raw(0x0052 | 5 << 8 | 3 << 12, nzk('m')); a.inv(0x71, vi, [5]); a.mro(5)        # original
        a.inv(0x6e, cat, [4, 5]); a.mro(4)
        a.cs(6, KVAL); a.inv(0x72, put, [0, 6, 4])
        return a.done()
    insert(c, 366, E2b)
    def E2a(p, na):   # entry: v8 = shot id (int param), v0..v2 free
        a = S(p); a.inv(0x71, vi, [8]); a.mro(0); a.inv(0x71, props, []); a.mro(1)
        a.cs(2, KID); a.inv(0x72, put, [1, 2, 0])
        return a.done()
    insert(c, 0, E2a); check(c); out[m] = c.build()

    # ---- E3 Loho.onDataAvailable (full rewrite, 16 regs: this v11, id v12, buf v13, v14, v15) ----
    m = one(d, 'Loho;', 'onDataAvailable'); c = Code(raw, d.code[m])
    w0 = c.w
    assert c.regs == 8 and c.ins == 5 and not c.tries
    f_a = w0[1]; f_b = w0[3]; s_a = w0[5]
    cap, alld, alloc, ro, clr, putb, pos, posI, lim, limI, ordr, ordI, cb = (
        w0[9], w0[13], w0[22], w0[26], w0[30], w0[33], w0[36], w0[40], w0[43], w0[47], w0[50], w0[54], w0[57])
    a = S(0)
    a.raw(0x0054 | 0 << 8 | 11 << 12, f_a)                  # iget-object v0, v11, a
    a.raw(0x0055 | 1 << 8 | 11 << 12, f_b)                  # iget-boolean v1, v11, b
    a.raw(0x0260, s_a)                                      # sget v2 (kept)
    a.b21(0x38, 1, 'heap')
    a.inv(0x6e, cap, [13]); a.mr(1); a.inv(0x71, alld, [1]); a.mro(1); a.go('copy')
    a.L('heap'); a.inv(0x6e, cap, [13]); a.mr(1); a.inv(0x71, alloc, [1]); a.mro(1)
    a.L('copy')
    a.inv(0x6e, ro, [13]); a.mro(2); a.inv(0x6e, clr, [2]); a.inv(0x6e, putb, [1, 2])
    a.inv(0x6e, pos, [13]); a.mr(2); a.inv(0x6e, posI, [1, 2])
    a.inv(0x6e, lim, [13]); a.mr(2); a.inv(0x6e, limI, [1, 2])
    a.inv(0x6e, ordr, [13]); a.mro(2); a.inv(0x6e, ordI, [1, 2])
    a.L('t0')
    a.inv(0x71, props, []); a.mro(2); a.cs(3, KVAL); a.inv(0x72, get, [2, 3]); a.mro(2); a.b21(0x38, 2, 'done')
    a.raw(0x021f, T(STR))
    a.inv(0x71, vi, [12]); a.mro(3); a.cs(4, COL); a.inv(0x6e, cat, [3, 4]); a.mro(3)
    a.inv(0x6e, sw, [2, 3]); a.mr(4); a.b21(0x38, 4, 'miss')
    a.inv(0x6e, ln, [3]); a.mr(4); a.inv(0x6e, sub1, [2, 4]); a.mro(2); a.go('build')
    a.L('miss'); a.cs(2, SL)
    a.L('build'); a.cs(3, FR); a.inv(0x6e, cat, [2, 3]); a.mro(2)
    a.c16(5, PH); a.cs(3, SP)
    a.L('pad'); a.inv(0x6e, cat, [2, 3]); a.mro(2); a.lit8(0xd8, 5, 5, -1); a.b21(0x3c, 5, 'pad')
    a.c4(3, 0); a.c16(4, PH); a.inv(0x6e, sub2, [2, 3, 4]); a.mro(2); a.inv(0x6e, gb, [2]); a.mro(3)   # v3 = new bytes
    a.cs(4, PHS); a.inv(0x6e, cat, [4, 4]); a.mro(4); a.inv(0x6e, gb, [4]); a.mro(4)               # v4 = placeholder
    a.inv(0x6e, blim, [1]); a.mr(5); a.c32(6, 65536); a.b22(0x37, 5, 6, 'lim'); a.raw(0x0501 | 6 << 12 & 0xffff)
    a.w[-1] = 0x01 | 5 << 8 | 6 << 12                                                               # move v5, v6
    a.L('lim'); a.lit8(0xd8, 5, 5, -PH); a.c4(6, 0)
    a.L('li'); a.b22(0x36, 6, 5, 'done')                                                             # if-gt v6,v5
    a.c4(7, 0)
    a.L('lj'); a.c16(10, PH); a.b22(0x35, 7, 10, 'found')                                            # if-ge v7,18
    a.raw(0x0090 | 8 << 8, 6 | 7 << 8); a.inv(0x6e, bget, [1, 8]); a.mr(8)                         # v8 = buf[i+j]
    a.raw(0x0048 | 9 << 8, 4 | 7 << 8); a.b22(0x33, 8, 9, 'ni')                                    # aget-byte v9 ; if-ne
    a.lit8(0xd8, 7, 7, 1); a.go('lj')
    a.L('found'); a.c4(7, 0)
    a.L('fl'); a.c16(10, PH); a.b22(0x35, 7, 10, 'af')
    a.raw(0x0090 | 8 << 8, 6 | 7 << 8); a.raw(0x0048 | 9 << 8, 3 | 7 << 8); a.inv(0x6e, bput, [1, 8, 9])
    a.lit8(0xd8, 7, 7, 1); a.go('fl')
    a.L('af'); a.lit8(0xd8, 6, 6, PH); a.go('li')
    a.L('ni'); a.lit8(0xd8, 6, 6, 1); a.go('li')
    a.L('t1')
    a.L('done'); a.inv(0x72, cb, [0, 12, 1, 14, 15]); a.raw(0x000e)
    w = a.done()
    c.w = w; c.regs = 16
    c.tries = [[a.lab['t0'], a.lab['t1'] - a.lab['t0'], 0]]; c.handlers = [[[], a.lab['done']]]
    check(c); out[m] = c.build()

    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
