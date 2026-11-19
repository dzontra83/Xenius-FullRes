"""Minimal DEX reader + Dalvik disassembler (read-only analysis)."""
import struct, sys

FMT = {}
NAME = {}
def op(rng, names, fmt):
    for i, o in enumerate(rng):
        FMT[o] = fmt
        NAME[o] = names[i] if isinstance(names, list) else names
op([0x00], 'nop', '10x'); op([0x01], 'move', '12x'); op([0x02], 'move/from16', '22x'); op([0x03], 'move/16', '32x')
op([0x04], 'move-wide', '12x'); op([0x05], 'move-wide/from16', '22x'); op([0x06], 'move-wide/16', '32x')
op([0x07], 'move-object', '12x'); op([0x08], 'move-object/from16', '22x'); op([0x09], 'move-object/16', '32x')
op(range(0x0a, 0x0e), ['move-result', 'move-result-wide', 'move-result-object', 'move-exception'], '11x')
op([0x0e], 'return-void', '10x'); op(range(0x0f, 0x12), ['return', 'return-wide', 'return-object'], '11x')
op([0x12], 'const/4', '11n'); op([0x13], 'const/16', '21s'); op([0x14], 'const', '31i'); op([0x15], 'const/high16', '21h')
op([0x16], 'const-wide/16', '21s'); op([0x17], 'const-wide/32', '31i'); op([0x18], 'const-wide', '51l'); op([0x19], 'const-wide/high16', '21h')
op([0x1a], 'const-string', '21c'); op([0x1b], 'const-string/jumbo', '31c'); op([0x1c], 'const-class', '21c')
op([0x1d], 'monitor-enter', '11x'); op([0x1e], 'monitor-exit', '11x'); op([0x1f], 'check-cast', '21c')
op([0x20], 'instance-of', '22c'); op([0x21], 'array-length', '12x'); op([0x22], 'new-instance', '21c'); op([0x23], 'new-array', '22c')
op([0x24], 'filled-new-array', '35c'); op([0x25], 'filled-new-array/range', '3rc'); op([0x26], 'fill-array-data', '31t')
op([0x27], 'throw', '11x'); op([0x28], 'goto', '10t'); op([0x29], 'goto/16', '20t'); op([0x2a], 'goto/32', '30t')
op([0x2b], 'packed-switch', '31t'); op([0x2c], 'sparse-switch', '31t')
op(range(0x2d, 0x32), ['cmpl-float', 'cmpg-float', 'cmpl-double', 'cmpg-double', 'cmp-long'], '23x')
op(range(0x32, 0x38), ['if-eq', 'if-ne', 'if-lt', 'if-ge', 'if-gt', 'if-le'], '22t')
op(range(0x38, 0x3e), ['if-eqz', 'if-nez', 'if-ltz', 'if-gez', 'if-gtz', 'if-lez'], '21t')
op(range(0x3e, 0x44), 'unused', '10x')
sfx = ['', '-wide', '-object', '-boolean', '-byte', '-char', '-short']
op(range(0x44, 0x4b), ['aget' + s for s in sfx], '23x'); op(range(0x4b, 0x52), ['aput' + s for s in sfx], '23x')
op(range(0x52, 0x59), ['iget' + s for s in sfx], '22c'); op(range(0x59, 0x60), ['iput' + s for s in sfx], '22c')
op(range(0x60, 0x67), ['sget' + s for s in sfx], '21c'); op(range(0x67, 0x6e), ['sput' + s for s in sfx], '21c')
inv = ['invoke-virtual', 'invoke-super', 'invoke-direct', 'invoke-static', 'invoke-interface']
op(range(0x6e, 0x73), inv, '35c'); op([0x73], 'unused', '10x'); op(range(0x74, 0x79), [i + '/range' for i in inv], '3rc')
op(range(0x79, 0x7b), 'unused', '10x')
op(range(0x7b, 0x90), ['neg-int', 'not-int', 'neg-long', 'not-long', 'neg-float', 'neg-double', 'int-to-long', 'int-to-float',
    'int-to-double', 'long-to-int', 'long-to-float', 'long-to-double', 'float-to-int', 'float-to-long', 'float-to-double',
    'double-to-int', 'double-to-long', 'double-to-float', 'int-to-byte', 'int-to-char', 'int-to-short'], '12x')
bin_ = []
for t in ['int', 'long']:
    bin_ += [x + '-' + t for x in ['add', 'sub', 'mul', 'div', 'rem', 'and', 'or', 'xor', 'shl', 'shr', 'ushr']]
for t in ['float', 'double']:
    bin_ += [x + '-' + t for x in ['add', 'sub', 'mul', 'div', 'rem']]
op(range(0x90, 0xb0), bin_, '23x'); op(range(0xb0, 0xd0), [b + '/2addr' for b in bin_], '12x')
op(range(0xd0, 0xd8), [x + '-int/lit16' for x in ['add', 'rsub', 'mul', 'div', 'rem', 'and', 'or', 'xor']], '22s')
op(range(0xd8, 0xe3), [x + '-int/lit8' for x in ['add', 'rsub', 'mul', 'div', 'rem', 'and', 'or', 'xor', 'shl', 'shr', 'ushr']], '22b')
op(range(0xe3, 0xfa), 'unused', '10x')
op([0xfa], 'invoke-polymorphic', '45cc'); op([0xfb], 'invoke-polymorphic/range', '4rcc')
op([0xfc], 'invoke-custom', '35c'); op([0xfd], 'invoke-custom/range', '3rc')
op([0xfe], 'const-method-handle', '21c'); op([0xff], 'const-method-type', '21c')
LEN = {'10x': 1, '12x': 1, '11n': 1, '11x': 1, '10t': 1, '20t': 2, '22x': 2, '21t': 2, '21s': 2, '21h': 2, '21c': 2, '23x': 2,
       '22b': 2, '22t': 2, '22s': 2, '22c': 2, '32x': 3, '30t': 3, '31t': 3, '31i': 3, '31c': 3, '35c': 3, '3rc': 3, '51l': 5,
       '45cc': 4, '4rcc': 4}


def uleb(b, p):
    v = sh = 0
    while True:
        z = b[p]; p += 1; v |= (z & 0x7f) << sh; sh += 7
        if z < 0x80:
            return v, p


def s16(x): return x - 0x10000 if x & 0x8000 else x
def s32(x): return x - 0x100000000 if x & 0x80000000 else x


class Dex:
    def __init__(self, path):
        self.b = b = open(path, 'rb').read()
        u = lambda o: struct.unpack_from('<I', b, o)[0]
        self.u32 = u
        self.u16 = lambda o: struct.unpack_from('<H', b, o)[0]
        n, off = u(0x38), u(0x3c)
        self.strings = []
        for i in range(n):
            so = u(off + 4 * i); _, p = uleb(b, so)
            e = b.index(b'\0', p)
            self.strings.append(b[p:e].decode('utf-8', 'replace'))
        n, off = u(0x40), u(0x44)
        self.types = [self.strings[u(off + 4 * i)] for i in range(n)]
        n, off = u(0x48), u(0x4c)
        self.protos = []
        for i in range(n):
            o = off + 12 * i; ret = self.types[u(o + 4)]; po = u(o + 8); ps = []
            if po:
                for j in range(u(po)): ps.append(self.types[self.u16(po + 4 + 2 * j)])
            self.protos.append((ret, ps))
        n, off = u(0x50), u(0x54)
        self.fields = [(self.types[self.u16(off + 8 * i)], self.types[self.u16(off + 8 * i + 2)], self.strings[u(off + 8 * i + 4)]) for i in range(n)]
        n, off = u(0x58), u(0x5c)
        self.methods = [(self.types[self.u16(off + 8 * i)], self.u16(off + 8 * i + 2), self.strings[u(off + 8 * i + 4)]) for i in range(n)]
        n, off = u(0x60), u(0x64)
        self.code = {}  # method idx -> code_off
        self.classes = {}
        for i in range(n):
            o = off + 32 * i
            cls = self.types[u(o)]; sup = u(o + 8); cd = u(o + 24)
            self.classes[cls] = (self.types[sup] if sup != 0xffffffff else None, cd)
            if not cd: continue
            p = cd
            sf, p = uleb(b, p); inf, p = uleb(b, p); dm, p = uleb(b, p); vm, p = uleb(b, p)
            for _ in range(sf + inf): _, p = uleb(b, p); _, p = uleb(b, p)
            for cnt in (dm, vm):
                mi = 0
                for _ in range(cnt):
                    d, p = uleb(b, p); mi += d; _, p = uleb(b, p); co, p = uleb(b, p)
                    if co: self.code[mi] = co

    def mname(self, i):
        c, pi, n = self.methods[i]; r, ps = self.protos[pi]
        return f'{c}->{n}({"".join(ps)}){r}'

    def fname(self, i):
        c, t, n = self.fields[i]; return f'{c}->{n}:{t}'

    def find(self, cls, name=None):
        return [i for i, (c, _, n) in enumerate(self.methods) if c == cls and (name is None or n == name)]

    def insns(self, mi):
        co = self.code[mi]
        regs, ins, outs, tries = self.u16(co), self.u16(co + 2), self.u16(co + 4), self.u16(co + 6)
        size = self.u32(co + 12)
        w = struct.unpack_from('<%dH' % size, self.b, co + 16)
        return (regs, ins, outs, tries), w

    def dis(self, mi):
        (regs, ins, outs, tries), w = self.insns(mi)
        out = [f'# {self.mname(mi)} regs={regs} ins={ins} outs={outs} tries={tries}']
        pc = 0
        while pc < len(w):
            x = w[pc]; o = x & 0xff
            if o == 0 and x in (0x100, 0x200, 0x300):
                if x == 0x100: ln = 4 + w[pc + 1] * 2
                elif x == 0x200: ln = 2 + w[pc + 1] * 4
                else:
                    ew = w[pc + 1]; cnt = w[pc + 2] | (w[pc + 3] << 16); ln = 4 + (ew * cnt + 1) // 2
                out.append(f'{pc:5d}: <payload {x:#x} len {ln}>'); pc += ln; continue
            f = FMT[o]; n = NAME[o]; a = (x >> 8) & 0xff; s = ''
            if f == '12x': s = f'v{a & 15}, v{a >> 4}'
            elif f == '11n': v = a >> 4; v = v - 16 if v & 8 else v; s = f'v{a & 15}, {v}'
            elif f == '11x': s = f'v{a}'
            elif f == '10t': s = f'-> {pc + (a - 256 if a & 128 else a)}'
            elif f == '20t': s = f'-> {pc + s16(w[pc + 1])}'
            elif f == '22x': s = f'v{a}, v{w[pc + 1]}'
            elif f == '21t': s = f'v{a}, -> {pc + s16(w[pc + 1])}'
            elif f == '21s': s = f'v{a}, {s16(w[pc + 1])}'
            elif f == '21h': s = f'v{a}, {w[pc + 1]:#x}<<'
            elif f == '21c':
                k = w[pc + 1]
                if n.startswith('const-string'): ref = repr(self.strings[k])
                elif n[1:4] in ('get', 'put'): ref = self.fname(k)
                else: ref = self.types[k] if k < len(self.types) else k
                s = f'v{a}, {ref}'
            elif f == '23x': s = f'v{a}, v{w[pc + 1] & 255}, v{w[pc + 1] >> 8}'
            elif f == '22b': c = w[pc + 1] >> 8; c = c - 256 if c & 128 else c; s = f'v{a}, v{w[pc + 1] & 255}, {c}'
            elif f == '22t': s = f'v{a & 15}, v{a >> 4}, -> {pc + s16(w[pc + 1])}'
            elif f == '22s': s = f'v{a & 15}, v{a >> 4}, {s16(w[pc + 1])}'
            elif f == '22c':
                k = w[pc + 1]; ref = self.fname(k) if n[1:4] in ('get', 'put') else self.types[k]
                s = f'v{a & 15}, v{a >> 4}, {ref}'
            elif f == '32x': s = f'v{w[pc + 1]}, v{w[pc + 2]}'
            elif f == '30t': s = f'-> {pc + s32(w[pc + 1] | w[pc + 2] << 16)}'
            elif f == '31t': s = f'v{a}, -> {pc + s32(w[pc + 1] | w[pc + 2] << 16)}'
            elif f == '31i': s = f'v{a}, {s32(w[pc + 1] | w[pc + 2] << 16)}'
            elif f == '31c': s = f'v{a}, {self.strings[w[pc + 1] | w[pc + 2] << 16]!r}'
            elif f in ('35c', '45cc'):
                cnt = a >> 4; g = a & 15; r = w[pc + 2]
                rs = [r & 15, (r >> 4) & 15, (r >> 8) & 15, r >> 12, g][:cnt]
                k = w[pc + 1]
                ref = self.mname(k) if n.startswith('invoke') and n != 'invoke-custom' else (self.types[k] if n.startswith('filled') else k)
                s = '{' + ', '.join(f'v{q}' for q in rs) + '}, ' + str(ref)
            elif f in ('3rc', '4rcc'):
                k = w[pc + 1]; c0 = w[pc + 2]
                ref = self.mname(k) if n.startswith('invoke') and 'custom' not in n else (self.types[k] if n.startswith('filled') else k)
                s = f'{{v{c0} .. v{c0 + a - 1}}}, {ref}'
            elif f == '51l': s = f'v{a}, {struct.unpack("<q", struct.pack("<4H", *w[pc + 1:pc + 5]))[0]}'
            out.append(f'{pc:5d}: {n} {s}')
            pc += LEN[f]
        return '\n'.join(out)

    def xrefs_string(self, sidx):
        """Methods whose code references string index."""
        hits = []
        for mi in self.code:
            _, w = self.insns(mi); pc = 0
            while pc < len(w):
                x = w[pc]; o = x & 0xff
                if o == 0 and x in (0x100, 0x200, 0x300):
                    if x == 0x100: pc += 4 + w[pc + 1] * 2
                    elif x == 0x200: pc += 2 + w[pc + 1] * 4
                    else: ew = w[pc + 1]; cnt = w[pc + 2] | (w[pc + 3] << 16); pc += 4 + (ew * cnt + 1) // 2
                    continue
                if o == 0x1a and w[pc + 1] == sidx: hits.append(mi); break
                if o == 0x1b and (w[pc + 1] | w[pc + 2] << 16) == sidx: hits.append(mi); break
                pc += LEN[FMT[o]]
        return hits

    def xrefs(self, kind, idx):
        """kind: 'method' (invoke) or 'field'."""
        hits = []
        for mi in self.code:
            _, w = self.insns(mi); pc = 0
            while pc < len(w):
                x = w[pc]; o = x & 0xff
                if o == 0 and x in (0x100, 0x200, 0x300):
                    if x == 0x100: pc += 4 + w[pc + 1] * 2
                    elif x == 0x200: pc += 2 + w[pc + 1] * 4
                    else: ew = w[pc + 1]; cnt = w[pc + 2] | (w[pc + 3] << 16); pc += 4 + (ew * cnt + 1) // 2
                    continue
                if kind == 'method' and (0x6e <= o <= 0x78) and w[pc + 1] == idx: hits.append(mi); break
                if kind == 'field' and (0x52 <= o <= 0x6d) and w[pc + 1] == idx: hits.append(mi); break
                pc += LEN[FMT[o]]
        return hits
