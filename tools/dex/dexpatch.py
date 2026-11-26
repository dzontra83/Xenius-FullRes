"""Dalvik code-item editing + DEX relocation (append rewritten code items to end of code section).

Layout assumption (checked): map order ... 0x2001 code_item, 0x2000 class_data_item, 0x1000 map_list (last).
"""
import struct, hashlib, zlib
from dex import FMT, LEN, NAME, uleb

def enc_uleb(v):
    o = bytearray()
    while True:
        z = v & 0x7f; v >>= 7
        o.append(z | 0x80 if v else z)
        if not v: return bytes(o)

def sleb(b, p):
    v = sh = 0
    while True:
        z = b[p]; p += 1; v |= (z & 0x7f) << sh; sh += 7
        if z < 0x80:
            if z & 0x40: v -= 1 << sh
            return v, p

def enc_sleb(v):
    o = bytearray()
    while True:
        z = v & 0x7f; v >>= 7
        if (v == 0 and not z & 0x40) or (v == -1 and z & 0x40):
            o.append(z); return bytes(o)
        o.append(z | 0x80)


class Code:
    """Parsed code_item."""
    def __init__(self, b, off):
        self.regs, self.ins, self.outs, ntries = struct.unpack_from('<HHHH', b, off)
        self.debug = struct.unpack_from('<I', b, off + 8)[0]
        n = struct.unpack_from('<I', b, off + 12)[0]
        self.w = list(struct.unpack_from('<%dH' % n, b, off + 16))
        p = off + 16 + 2 * n
        if ntries and n % 2: p += 2
        self.tries = []  # [start, count, handler_index]
        raw = []
        for i in range(ntries):
            s, c, h = struct.unpack_from('<IHH', b, p + 8 * i); raw.append((s, c, h))
        self.handlers = []  # list of (pairs[(type,addr)], catchall or None)
        if ntries:
            hb = p + 8 * ntries
            cnt, q = uleb(b, hb)
            offmap = {}
            for i in range(cnt):
                ho = q - hb
                sz, q = sleb(b, q)
                pairs = []
                for _ in range(abs(sz)):
                    t, q = uleb(b, q); a, q = uleb(b, q); pairs.append([t, a])
                ca = None
                if sz <= 0:
                    ca, q = uleb(b, q)
                offmap[ho] = len(self.handlers)
                self.handlers.append([pairs, ca])
            for s, c, h in raw: self.tries.append([s, c, offmap[h]])
        self.end = q if ntries else p

    def build(self):
        out = bytearray(struct.pack('<HHHHII', self.regs, self.ins, self.outs, len(self.tries), self.debug, len(self.w)))
        out += struct.pack('<%dH' % len(self.w), *self.w)
        if self.tries:
            if len(self.w) % 2: out += b'\0\0'
            hl = bytearray(enc_uleb(len(self.handlers))); hoff = []
            for pairs, ca in self.handlers:
                hoff.append(len(hl))
                hl += enc_sleb(len(pairs) if ca is None else -len(pairs))
                for t, a in pairs: hl += enc_uleb(t) + enc_uleb(a)
                if ca is not None: hl += enc_uleb(ca)
            for s, c, h in self.tries: out += struct.pack('<IHH', s, c, hoff[h])
            out += hl
        return bytes(out)


def walk(w):
    """Yield (pc, length, is_payload)."""
    pc = 0
    while pc < len(w):
        x = w[pc]; o = x & 0xff
        if o == 0 and x in (0x100, 0x200, 0x300):
            if x == 0x100: ln = 4 + w[pc + 1] * 2
            elif x == 0x200: ln = 2 + w[pc + 1] * 4
            else: ln = 4 + (w[pc + 1] * (w[pc + 2] | w[pc + 3] << 16) + 1) // 2
            yield pc, ln, True
        else:
            ln = LEN[FMT[o]]; yield pc, ln, False
        pc += ln

def s16(x): return x - 0x10000 if x & 0x8000 else x
def s32(x): return x - 0x100000000 if x & 0x80000000 else x

def branches(w):
    """Return list of (pc, fmt, target) for relative branches and payload refs; plus switch payload targets."""
    res = []; sw = []
    for pc, ln, pay in walk(w):
        if pay: continue
        o = w[pc] & 0xff; f = FMT[o]; a = w[pc] >> 8
        if f == '10t': res.append((pc, f, pc + (a - 256 if a & 128 else a)))
        elif f == '20t': res.append((pc, f, pc + s16(w[pc + 1])))
        elif f in ('21t', '22t'): res.append((pc, f, pc + s16(w[pc + 1])))
        elif f in ('30t', '31t'):
            t = pc + s32(w[pc + 1] | w[pc + 2] << 16); res.append((pc, f, t))
            if o in (0x2b, 0x2c): sw.append((pc, t))
    return res, sw

def switch_targets(w, swpc, paypc):
    x = w[paypc]; n = w[paypc + 1]; out = []
    if x == 0x100:
        for i in range(n):
            q = paypc + 4 + 2 * i; out.append((q, swpc + s32(w[q] | w[q + 1] << 16)))
    else:
        for i in range(n):
            q = paypc + 2 + 2 * n + 2 * i; out.append((q, swpc + s32(w[q] | w[q + 1] << 16)))
    return out

def boundaries(w):
    return {pc for pc, ln, pay in walk(w) if not pay}


def insert(code, p, block_fn):
    """Insert instructions before instruction at pc p.
    block_fn(L_map) -> list of words. Inside the block, branches use absolute *new* addresses via helper
    `rel(src_new, dst_new)`; block_fn receives (base=p, newaddr=f(old)) so it can compute targets.
    Branches into p from elsewhere land at the start of the block."""
    w = code.w
    assert p in boundaries(w), 'p not an instruction boundary'
    probe = block_fn(p, lambda a: a)  # length probe
    L = len(probe)
    if L % 2: L += 1  # keep payload 4-byte alignment
    def na(a):  # new address of old address a (branch target semantics: a==p -> block start)
        return a if a <= p else a + L
    def na_insn(a):  # new address of old instruction a (instruction itself moves when a>=p)
        return a if a < p else a + L
    blk = block_fn(p, lambda a: a + L if a >= p else a)  # block jumps to old instr a (>=p) -> moved location
    if len(blk) % 2: blk = blk + [0]
    assert len(blk) == L
    br, sw = branches(w)
    nw = w[:p] + blk + w[p:]
    for pc, f, t in br:
        npc = na_insn(pc); nt = na(t); off = nt - npc
        if f == '10t':
            assert -128 <= off <= 127, ('10t overflow', pc); nw[npc] = (nw[npc] & 0xff) | ((off & 0xff) << 8)
        elif f in ('20t', '21t', '22t'):
            assert -32768 <= off <= 32767, ('16-bit branch overflow', pc); nw[npc + 1] = off & 0xffff
        else:
            nw[npc + 1] = off & 0xffff; nw[npc + 2] = (off >> 16) & 0xffff
    for swpc, paypc in sw:
        for q, t in switch_targets(w, swpc, paypc):
            nq = na_insn(q); off = na(t) - na_insn(swpc)
            nw[nq] = off & 0xffff; nw[nq + 1] = (off >> 16) & 0xffff
    for tr in code.tries:
        s, c = tr[0], tr[1]; e = s + c
        ns = na_insn(s); ne = e if e <= p else e + L
        if s < p < e: pass  # block inside try range
        tr[0], tr[1] = ns, ne - ns
    for pairs, ca in code.handlers:
        for pr in pairs: pr[1] = na_insn(pr[1])
    if ca_list := [h for h in code.handlers if h[1] is not None]:
        for h in ca_list: h[1] = na_insn(h[1])
    code.w = nw
    return L


def check(code):
    w = code.w; bd = boundaries(w)
    br, sw = branches(w)
    for pc, f, t in br:
        if (w[pc] & 0xff) in (0x26, 0x2b, 0x2c):
            assert w[t] in (0x100, 0x200, 0x300) and t % 2 == 0, ('payload ref bad', pc, t)
        else:
            assert t in bd, ('branch to non-boundary', pc, t)
    for swpc, paypc in sw:
        for q, t in switch_targets(w, swpc, paypc): assert t in bd, ('switch target', swpc, t)
    for s, c, h in code.tries:
        assert s in bd and (s + c in bd or s + c == len(w)), ('try range', s, c)
    for pairs, ca in code.handlers:
        for _, a in pairs: assert a in bd, ('handler', a)
        if ca is not None: assert ca in bd
    # last instruction must not fall off
    return True


def relocate(dexbytes, newcodes):
    """newcodes: {method_idx: code_item_bytes}. Returns new dex bytes."""
    b = bytearray(dexbytes)
    u32 = lambda o: struct.unpack_from('<I', b, o)[0]
    mapoff = u32(0x34); n = u32(mapoff)
    ents = [list(struct.unpack_from('<HHII', b, mapoff + 4 + 12 * i)) for i in range(n)]
    types = [e[0] for e in ents]
    assert types[-3:] == [0x2001, 0x2000, 0x1000], types
    cd_start = ents[-2][3]; cls_cnt = ents[-2][2]
    code_count = ents[-3][2]
    head = bytes(b[:cd_start])
    # new code items appended at cd_start (4-aligned)
    assert cd_start % 4 == 0
    blob = bytearray(); newoff = {}
    for mi, cb in newcodes.items():
        while len(blob) % 4: blob += b'\0'
        newoff[mi] = cd_start + len(blob); blob += cb
    while len(blob) % 4: blob += b'\0'
    # rebuild class_data section
    cdefs_n, cdefs_off = u32(0x60), u32(0x64)
    cdoff_of_class = {}
    for i in range(cdefs_n):
        o = u32(cdefs_off + 32 * i + 24)
        if o: cdoff_of_class.setdefault(o, []).append(i)
    # parse every class_data item in section order
    p = cd_start; items = []
    for _ in range(cls_cnt):
        start = p
        sf, p = uleb(b, p); inf, p = uleb(b, p); dm, p = uleb(b, p); vm, p = uleb(b, p)
        fields = []
        for _ in range(sf + inf):
            a, p = uleb(b, p); c, p = uleb(b, p); fields.append((a, c))
        meths = []
        for cnt in (dm, vm):
            mi = 0; lst = []
            for _ in range(cnt):
                dlt, p = uleb(b, p); mi += dlt; af, p = uleb(b, p); co, p = uleb(b, p)
                lst.append([dlt, mi, af, co])
            meths.append(lst)
        items.append((start, sf, inf, fields, meths))
    end_cd = p
    assert end_cd <= ents[-1][3]
    newsec = bytearray(); oldnew = {}; replaced = set()
    base = cd_start + len(blob)
    for start, sf, inf, fields, meths in items:
        oldnew[start] = base + len(newsec)
        newsec += enc_uleb(sf) + enc_uleb(inf) + enc_uleb(len(meths[0])) + enc_uleb(len(meths[1]))
        for a, c in fields: newsec += enc_uleb(a) + enc_uleb(c)
        for lst in meths:
            for dlt, mi, af, co in lst:
                if mi in newoff: co = newoff[mi]; replaced.add(mi)
                newsec += enc_uleb(dlt) + enc_uleb(af) + enc_uleb(co)
    assert replaced == set(newoff), set(newoff) - replaced
    gap = bytes(b[end_cd:ents[-1][3]])  # padding before map
    tail_start = base + len(newsec) + len(gap)
    pad = (-tail_start) % 4
    newmapoff = tail_start + pad
    out = bytearray(head) + blob + newsec + gap + b'\0' * pad
    mapb = bytearray(b[ents[-1][3]:])
    out += mapb
    # fix class_def class_data_off
    for i in range(cdefs_n):
        o = cdefs_off + 32 * i + 24; v = u32(o)
        if v: struct.pack_into('<I', out, o, oldnew[v])
    # fix map entries
    struct.pack_into('<I', out, 0x34, newmapoff)
    ents[-3][2] = code_count + len(newcodes)
    ents[-2][3] = base
    ents[-1][3] = newmapoff
    for i, e in enumerate(ents): struct.pack_into('<HHII', out, newmapoff + 4 + 12 * i, *e)
    data_off = u32(0x6c)
    struct.pack_into('<I', out, 0x68, len(out) - data_off)  # data_size
    struct.pack_into('<I', out, 0x20, len(out))  # file_size
    out[12:32] = hashlib.sha1(out[32:]).digest()
    struct.pack_into('<I', out, 8, zlib.adler32(bytes(out[12:])) & 0xffffffff)
    return bytes(out)
