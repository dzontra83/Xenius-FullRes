#!/usr/bin/env python3
"""XENIUS P157 — shutter-to-ready experiment, on top of P156 (classes2.dex unchanged).

S  Streaming hand-off to HDR+ (Ldvm.p). Before: the feeder waited for the LAST 50 MP frame of the burst before
   giving frame 1 to HDR+, then fed all N back-to-back, so GCam's "capture finished" (shutter ready) came only after
   the last frame arrived + N addPayloadFrame calls. Now each frame is fed as soon as it lands:
   S1 first-frame wait (pc 604): wait for slot 1 instead of slot N (same 10 s timeout).
   S2 slot 1/2 occupancy markers are no longer removed by the feeder (remove -> get), so the image listener can't
      put a later frame back into slot 1/2 mid-burst. Llei's burst-start cleanup still clears them for the next shot.
   S3 slot 2 (pc 924): wait up to 3 s for the frame before feeding it.
   S4 slots 3..25 (pc 1261): wait up to 3 s for the frame, then take it with put(slot, 'applied') instead of
      remove(slot): atomic, and the placeholder keeps the listener from reusing the slot (it fills the first empty
      one). Burst-start cleanup removes placeholders (it only closes Image objects).
F  Frame cap 25 -> 15 (Llei clamp). Frame settings above 15 shoot 15 frames; 2..15 unchanged.

Run: python3 build_p157.py XENIUS_P156_FLUSH_UNSIGNED.apk XENIUS_P157_STREAM15_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr

P156_DEX = 'b4c95194'
CAP = 15
SLOT_WAIT = 300          # x10 ms


class A:
    def __init__(self, base): self.base = base; self.w = []; self.fix = []; self.lab = {}
    def pc(self): return self.base + len(self.w)
    def label(self, n): self.lab[n] = self.pc()
    def cstr(self, a, s): self.w += [0x1a | a << 8, s]
    def const16(self, a, v): self.w += [0x13 | a << 8, v & 0xffff]
    def constw16(self, a, v): self.w += [0x16 | a << 8, v & 0xffff]
    def addlit8(self, a, b, v): self.w += [0xd8 | a << 8, b | (v & 0xff) << 8]
    def inv(self, op, m, regs):
        p = 0
        for i, r in enumerate(regs): assert r < 16; p |= r << (4 * i)
        self.w += [op | len(regs) << 12, m, p]
    def mresobj(self, a): self.w += [0x0c | a << 8]
    def br(self, op, a, t): self.fix.append((len(self.w), self.pc(), t)); self.w += [op | a << 8, 0]
    def done(self):
        for i, src, t in self.fix:
            off = self.lab[t] - src; assert -32768 <= off < 32768; self.w[i + 1] = off & 0xffff
        return self.w


def wait_loop(a, ids, key_reg, key=None):
    """v2 <- props.get(key) until non-null or SLOT_WAIT x 10 ms. Uses v0 (props), v2, v3, v4."""
    if key is not None: a.cstr(key_reg, key)
    a.const16(4, SLOT_WAIT)
    a.label('loop')
    a.inv(0x72, ids['get'], [0, key_reg]); a.mresobj(2)
    a.br(0x39, 2, 'out')                                   # if-nez v2, out
    a.constw16(2, 10); a.inv(0x71, ids['sleep'], [2, 3])   # SystemClock.sleep(10)
    a.addlit8(4, 4, -1)
    a.br(0x3c, 4, 'loop')                                  # if-gtz v4, loop
    a.label('out')


def patch(raw):
    assert hashlib.sha256(raw).hexdigest().startswith(P156_DEX), 'classes.dex is not P156'
    open('/tmp/_p157.dex', 'wb').write(raw); d = Dex('/tmp/_p157.dex')
    MAP = 'Ljava/util/Map;'
    ids = dict(get=mid(d, MAP, 'get', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               remove=mid(d, MAP, 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               put=mid(d, MAP, 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;'),
               sleep=mid(d, 'Landroid/os/SystemClock;', 'sleep', '(J)V'))

    # ---- F: Llei clamp 25 -> 15 (in place) ----
    b = bytearray(raw)
    m = one(d, 'Llei;', 'onCaptureCompleted'); base = d.code[m] + 16
    (_, _, _, _), w = d.insns(m); w = list(w)
    assert w[475:477] == [0x0213, 25] and w[477] & 0xff == 0x36, (hex(w[475]), w[476])   # const/16 v2,25 ; if-gt
    struct.pack_into('<H', b, base + 2 * 476, CAP)
    raw = bytes(b)

    # ---- S: Ldvm.p ----
    m = one(d, 'Ldvm;', 'p'); c = Code(raw, d.code[m]); w = c.w
    rem = lambda pc: w[pc:pc + 3] == [0x2072, ids['remove'], 0x0010]          # invoke-interface {v0,v1} remove
    # S2 in place: marker removes -> get
    assert w[651:653] == [0x011a, sid(d, 'getAHardwareBufferPtr')] and rem(653)
    assert w[659:661] == [0x011a, sid(d, 'new_RawWriteView__SWIG_1')] and rem(661)
    assert w[656] & 0xff == 0x2a and w[664] & 0xff == 0x20     # goto/32 ; instance-of (results unused before)
    w[654] = w[662] = ids['get']
    # inserts, highest pc first
    assert rem(1261) and w[1264] == 0x020c and w[1265] & 0xff == 0x38, [hex(x) for x in w[1261:1266]]
    def S4(p, na):
        a = A(p); wait_loop(a, ids, 1)
        a.cstr(3, sid(d, 'applied'))
        return a.done()
    n0 = len(c.w); insert(c, 1261, S4); w2 = c.w
    hits = [1261 + len(w2) - n0]
    assert w2[hits[0]:hits[0] + 3] == [0x2072, ids['remove'], 0x0010]
    w2[hits[0]:hits[0] + 3] = [0x3072, ids['put'], 0x0310]                   # invoke-interface {v0,v1,v3} put

    assert w2[924:926] == [0x011a, sid(d, 'getTimestamp')], hex(w2[924])
    def S3(p, na):
        a = A(p); wait_loop(a, ids, 1, sid(d, 'getTimestamp')); return a.done()
    insert(c, 924, S3)

    assert c.w[604:606] == [0x0613, 1000], [hex(x) for x in c.w[604:606]]     # const/16 v6,1000 (C2 wait)
    def S1(p, na):
        a = A(p); a.cstr(0, sid(d, 'getHardwareBuffer')); return a.done()
    insert(c, 604, S1)
    check(c)

    out = bytearray(relocate(raw, {m: c.build()}))
    fix_hdr(out)
    return bytes(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
