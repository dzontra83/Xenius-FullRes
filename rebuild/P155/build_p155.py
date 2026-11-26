#!/usr/bin/env python3
"""XENIUS P155 — key40 gate hardening, on top of P154B.

classes2.dex, LMC/c2a.getC2apiPref (the key40 gate every acquire/release goes through: K1-K4, D, E/F):
  after `setValue(40, target)` + `sleep(200)` the value is now READ BACK. If the vendor service has not taken it
  (setValue is a one-way Binder call), it is written again and re-checked: up to 3 attempts, 300 ms apart.
  Log: `VIVO_GATE <value read back>`; `VIVO_GATE -1` if key40 never reached the target.
Because K4 (before the 50 MP session) and D (before every openCamera) already call this gate, key40 is now
verified both before open and right before the 50 MP streams are configured.
classes.dex is unchanged from P154B.

Run: python3 build_p155.py XENIUS_P154B_QUIET_UNSIGNED.apk XENIUS_P155_KEY40_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import rebuild_apk, one, mid, sid


class A:
    """Tiny assembler with label fix-ups (21t/22t/30t)."""
    def __init__(self, base): self.base = base; self.w = []; self.fix = []; self.lab = {}
    def pc(self): return self.base + len(self.w)
    def label(self, n): self.lab[n] = self.pc()
    def raw(self, *ws): self.w += list(ws)
    def const4(self, a, v): assert a < 16 and -8 <= v < 8; self.w += [0x12 | a << 8 | (v & 15) << 12]
    def const16(self, a, v): self.w += [0x13 | a << 8, v & 0xffff]
    def constw16(self, a, v): self.w += [0x16 | a << 8, v & 0xffff]
    def cstr(self, a, s): self.w += [0x1a | a << 8, s]
    def newarr(self, a, b, t): assert a < 16 and b < 16; self.w += [0x23 | a << 8 | b << 12, t]
    def sgetobj(self, a, f): self.w += [0x62 | a << 8, f]
    def aputobj(self, a, arr, idx): self.w += [0x4d | a << 8, arr | idx << 8]
    def ccast(self, a, t): self.w += [0x1f | a << 8, t]
    def addlit8(self, a, b, v): self.w += [0xd8 | a << 8, b | (v & 0xff) << 8]
    def inv(self, op, m, regs):
        assert len(regs) <= 5 and all(r < 16 for r in regs)
        g = regs[4] if len(regs) == 5 else 0; packed = 0
        for i, r in enumerate(regs[:4]): packed |= r << (4 * i)
        self.w += [op | len(regs) << 12 | g << 8, m, packed]
    def static(self, m, regs): self.inv(0x71, m, regs)
    def virtual(self, m, regs): self.inv(0x6e, m, regs)
    def mres(self, a): self.w += [0x0a | a << 8]
    def mresobj(self, a): self.w += [0x0c | a << 8]
    def if_eq(self, a, b, t): self.fix.append((len(self.w), self.pc(), t, 22)); self.w += [0x32 | a << 8 | b << 12, 0]
    def if_eqz(self, a, t): self.fix.append((len(self.w), self.pc(), t, 21)); self.w += [0x38 | a << 8, 0]
    def goto(self, t): self.fix.append((len(self.w), self.pc(), t, 30)); self.w += [0x2a, 0, 0]
    def done(self):
        for i, src, t, f in self.fix:
            dst = self.lab[t] if isinstance(t, str) else t; off = dst - src
            if f in (21, 22): assert -32768 <= off < 32768; self.w[i + 1] = off & 0xffff
            else: self.w[i + 1] = off & 0xffff; self.w[i + 2] = (off >> 16) & 0xffff
        return self.w


def patch_classes2(raw):
    open('/tmp/_p155c2.dex', 'wb').write(raw); d = Dex('/tmp/_p155c2.dex')
    m = one(d, 'LMC/c2a;', 'getC2apiPref'); c = Code(d.b, d.code[m])
    assert c.regs == 14 and c.ins == 1, (c.regs, c.ins)
    # locate: invoke-static {v2,v3} Thread.sleep(J) ; const-string v1, 'VIVO_GATE'  (the verified write path)
    sleep = mid(d, 'Ljava/lang/Thread;', 'sleep', '(J)V')
    s_gate = sid(d, 'VIVO_GATE')
    P = None
    for pc in range(len(c.w) - 5):
        if c.w[pc] == 0x2071 and c.w[pc + 1] == sleep and c.w[pc + 2] == 0x32 and \
                c.w[pc + 3] == (0x1a | 1 << 8) and c.w[pc + 4] == s_gate:
            P = pc + 3; break
    assert P is not None, 'gate write path not found'
    getm = mid(d, 'Ljava/lang/Class;', 'getMethod', '(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;')
    minv = mid(d, 'Ljava/lang/reflect/Method;', 'invoke', '(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;')
    valueOf = mid(d, 'Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    intValue = mid(d, 'Ljava/lang/Integer;', 'intValue', '()I')
    toStr = mid(d, 'Ljava/lang/Integer;', 'toString', '(I)Ljava/lang/String;')
    logi = mid(d, 'Landroid/util/Log;', 'i', '(Ljava/lang/String;Ljava/lang/String;)I')
    TYPE = [i for i, f in enumerate(d.fields) if f[0] == 'Ljava/lang/Integer;' and f[2] == 'TYPE'][0]
    t_cls = d.types.index('[Ljava/lang/Class;'); t_obj = d.types.index('[Ljava/lang/Object;')
    t_int = d.types.index('Ljava/lang/Integer;')
    s_get, s_set = sid(d, 'getInfo'), sid(d, 'setValue')

    # live at P: v0 = VivoCameraManager Class, v6 = instance, v10 = target value, v13 = p0. Free: v1-v4, v7-v9, v11, v12.
    def blk(p, na):
        a = A(p)
        a.const4(12, 3)                                         # attempts left
        a.label('read')
        a.const4(8, 1); a.newarr(9, 8, t_cls); a.sgetobj(8, TYPE); a.const4(7, 0); a.aputobj(8, 9, 7)
        a.cstr(1, s_get); a.virtual(getm, [0, 1, 9]); a.mresobj(11)
        a.const4(8, 1); a.newarr(7, 8, t_obj); a.const16(1, 40); a.static(valueOf, [1]); a.mresobj(1)
        a.const4(8, 0); a.aputobj(1, 7, 8)
        a.virtual(minv, [11, 6, 7]); a.mresobj(4); a.ccast(4, t_int); a.virtual(intValue, [4]); a.mres(4)
        a.if_eq(4, 10, 'log')                                   # confirmed
        a.addlit8(12, 12, -1)
        a.if_eqz(12, 'fail')
        # write again: setValue(40, target)
        a.const4(8, 2); a.newarr(9, 8, t_cls); a.sgetobj(8, TYPE); a.const4(7, 0); a.aputobj(8, 9, 7)
        a.const4(7, 1); a.aputobj(8, 9, 7)
        a.cstr(1, s_set); a.virtual(getm, [0, 1, 9]); a.mresobj(11)
        a.const4(8, 2); a.newarr(7, 8, t_obj); a.const16(1, 40); a.static(valueOf, [1]); a.mresobj(1)
        a.const4(8, 0); a.aputobj(1, 7, 8); a.static(valueOf, [10]); a.mresobj(1); a.const4(8, 1); a.aputobj(1, 7, 8)
        a.virtual(minv, [11, 6, 7]); a.mresobj(1)
        a.constw16(2, 300); a.static(sleep, [2, 3])
        a.goto('read')
        a.label('fail')
        a.const4(4, -1)
        a.label('log')
        a.cstr(1, s_gate); a.static(toStr, [4]); a.mresobj(2); a.static(logi, [1, 2]); a.mres(1)
        a.goto(na(P))                                           # continue with the original VIVO_GATE log
        return a.done()
    insert(c, P, blk); check(c)
    return relocate(raw, {m: c.build()})


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src)
    c1 = z.read('classes.dex')
    assert hashlib.sha256(c1).hexdigest() == 'b3482bcab02c1073aae6954db17e3d6888dbf25a52dbd814a1e0949116f0cbca', 'not P154B'
    c2 = patch_classes2(z.read('classes2.dex'))
    rebuild_apk(src, dst, {'classes2.dex': c2})
    print('classes2.dex sha256', hashlib.sha256(c2).hexdigest())
    print('wrote', dst)
