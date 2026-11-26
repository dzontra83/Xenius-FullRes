#!/usr/bin/env python3
"""XENIUS P149A — RES button selects 12 MP (OFF) or 50 MP FullRes (ON). Built on P151K13.

RES = LMC/UI/Button/Upscale, pref `pref_upscale_key` (0/1); tapping it already calls CameraActivity.ReInit()
(onPause/onStop/onStart/onResume), so the camera is reopened with the new mode.

classes.dex
  A  Llel.c   (GCam session creation)      RES=0: no 8192x6144 RAW16 ImageReader; drop stale RAW50 state
  B  Llfe.e   (other session output lists) RES=0: same
  C  AeShotParams.j / .k                   upscale target size never applied (RES no longer means upscale)
classes2.dex
  E  LMC/c2a.getC2apiPref(null) acquire    RES=0: do not touch key40 (release path unchanged)
Everything else, including all K13 50 MP / HDR+ / ID9 code, is byte-identical.
"""
import sys, struct, zipfile, hashlib
sys.path.insert(0, __import__('os').path.dirname(__file__))
from dex import Dex
from dexpatch import Code, insert, check, relocate

K13_DEX_SHA = '840d635502613b999ef70d834fcb4096bb75f04020e54d22c2d7d40f2fbbf5d5'

# ---- tiny assembler -------------------------------------------------------
class Asm:
    def __init__(self, base): self.base = base; self.w = []; self.fix = []; self.lab = {}
    def pc(self): return self.base + len(self.w)
    def label(self, n): self.lab[n] = self.pc()
    def const_string(self, v, s): assert s < 65536 and v < 256; self.w += [0x1a | v << 8, s]
    def invoke(self, op, m, regs):
        assert len(regs) <= 5 and all(r < 16 for r in regs)
        g = regs[4] if len(regs) == 5 else 0
        packed = 0
        for i, r in enumerate(regs[:4]): packed |= r << (4 * i)
        self.w += [op | (len(regs) << 12) | (g << 8), m, packed]
    def inv_static(self, m, regs): self.invoke(0x71, m, regs)
    def inv_virtual(self, m, regs): self.invoke(0x6e, m, regs)
    def inv_iface(self, m, regs): self.invoke(0x72, m, regs)
    def move_result(self, v): self.w += [0x0a | v << 8]
    def move_result_obj(self, v): self.w += [0x0c | v << 8]
    def check_cast(self, v, t): self.w += [0x1f | v << 8, t]
    def iget_obj(self, a, b, f): assert a < 16 and b < 16; self.w += [0x54 | (b << 12) | (a << 8), f]
    def ret_obj(self, v): self.w += [0x11 | v << 8]
    def _br(self, op, v, target):  # 21t, target absolute or label name
        self.fix.append((len(self.w), self.pc(), target, '21t')); self.w += [op | v << 8, 0]
    def if_eqz(self, v, t): self._br(0x38, v, t)
    def if_nez(self, v, t): self._br(0x39, v, t)
    def goto32(self, t): self.fix.append((len(self.w), self.pc(), t, '30t')); self.w += [0x2a, 0, 0]
    def done(self):
        for i, src, t, f in self.fix:
            dst = self.lab[t] if isinstance(t, str) else t; off = dst - src
            if f == '21t': assert -32768 <= off < 32768; self.w[i + 1] = off & 0xffff
            else: self.w[i + 1] = off & 0xffff; self.w[i + 2] = (off >> 16) & 0xffff
        return self.w

def one(d, cls, name):
    r = d.find(cls, name); assert len(r) == 1, (cls, name, r); return r[0]
def mid(d, cls, name, proto):
    r = [i for i, (c, p, n) in enumerate(d.methods) if c == cls and n == name and d.mname(i).endswith(proto)]
    assert len(r) == 1, (cls, name, r); return r[0]
def sid(d, s): return d.strings.index(s)

def drop_raw50_state(a, d, rp, rk, ids):
    """rp, rk scratch regs (<16). Removes stale 50 MP objects; closes stale RAW50 ImageReader."""
    a.inv_static(ids['getProperties'], []); a.move_result_obj(rp)
    for key in ('getHardwareBuffer', 'getTimestamp'):
        a.const_string(rk, sid(d, key)); a.inv_iface(ids['remove'], [rp, rk])
    a.const_string(rk, sid(d, 'RAW50_REQ')); a.inv_iface(ids['remove'], [rp, rk]); a.move_result_obj(rk)
    a.if_eqz(rk, 'noreader')
    a.check_cast(rk, ids['ImageReader']); a.inv_virtual(ids['close'], [rk])
    a.label('noreader')
    a.const_string(rp, sid(d, 'RESOLUTION_SWITCH')); a.const_string(rk, sid(d, 'skip'))
    a.inv_static(ids['logi'], [rp, rk])


def patch_classes(raw):
    assert hashlib.sha256(raw).hexdigest() == K13_DEX_SHA, 'classes.dex is not the K13 checkpoint'
    open('/tmp/_c1.dex', 'wb').write(raw); d = Dex('/tmp/_c1.dex')
    ids = dict(getProperties=mid(d, 'Ljava/lang/System;', 'getProperties', ')Ljava/util/Properties;'),
               remove=mid(d, 'Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               close=mid(d, 'Landroid/media/ImageReader;', 'close', '()V'),
               logi=mid(d, 'Landroid/util/Log;', 'i', '(Ljava/lang/String;Ljava/lang/String;)I'),
               menu=mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I'),
               ImageReader=d.types.index('Landroid/media/ImageReader;'))
    fld_c = [i for i, f in enumerate(d.fields) if f == ('Lljq;', 'Ljava/util/concurrent/Executor;', 'c')][0]
    s_res = sid(d, 'pref_upscale_key')
    new = {}

    # ---- A: Llel.c, insert before pc 12 (goto/16 -> 64, the RAW50 reader block) ----
    m = one(d, 'Llel;', 'c'); c = Code(d.b, d.code[m])
    assert c.w[12] == 0x0029 and c.w[13] == 52 and c.w[14] == 0x0422, 'Llel.c layout changed'
    assert c.w[134:136] == [0x7354, fld_c], 'Llel.c executor load moved'
    def blkA(p, na):
        a = Asm(p)
        a.const_string(13, s_res); a.inv_static(ids['menu'], [13]); a.move_result(13)
        a.if_nez(13, na(12))                       # RES ON -> original goto 64 (50 MP reader)
        drop_raw50_state(a, d, 12, 13, ids)
        a.iget_obj(3, 7, fld_c)                     # v3 = lljq.c (Executor), as at pc 134
        a.goto32(na(14))                            # continue SessionConfiguration build without RAW50
        return a.done()
    insert(c, 12, blkA); check(c); new[m] = c

    # ---- B: Llfe.e, insert before pc 44 (const/16 v5, 8192) ----
    m = one(d, 'Llfe;', 'e'); c = Code(d.b, d.code[m])
    assert c.w[44] == 0x0513 and c.w[45] == 8192, 'Llfe.e layout changed'
    def blkB(p, na):
        a = Asm(p)
        a.const_string(5, s_res); a.inv_static(ids['menu'], [5]); a.move_result(5)
        a.if_nez(5, na(44))
        drop_raw50_state(a, d, 6, 7, ids)
        a.ret_obj(0)                                # outputs without RAW50
        return a.done()
    insert(c, 44, blkB); check(c); new[m] = c

    builds = {k: v.build() for k, v in new.items()}
    out = bytearray(relocate(raw, builds))

    # ---- C: AeShotParams.j/.k in place: 'if-nez v1,+3' -> 2x nop (never upscale) ----
    for n in ('j', 'k'):
        m = one(d, 'Lcom/google/googlex/gcam/AeShotParams;', n); co = d.code[m]
        ins = co + 16
        w = list(struct.unpack_from('<4H', out, ins + 6 * 2 - 0))  # words 6..9 (code_item untouched by relocate)
        assert w[0] == 0x0139 and w[1] == 3 and w[2] == 0x000e, (n, w)
        struct.pack_into('<2H', out, ins + 12, 0, 0)
    import hashlib as h, zlib
    out[12:32] = h.sha1(out[32:]).digest(); struct.pack_into('<I', out, 8, zlib.adler32(bytes(out[12:])) & 0xffffffff)
    return bytes(out), list(new)


def patch_classes2(raw):
    open('/tmp/_c2.dex', 'wb').write(raw); d = Dex('/tmp/_c2.dex')
    m = one(d, 'LMC/c2a;', 'getC2apiPref'); c = Code(d.b, d.code[m])
    aem = [i for i, f in enumerate(d.fields) if f[0] == 'LMC/main;' and f[2] == 'Aemodef'][0]
    assert c.w[338:340] == [0x0460, aem], 'getC2apiPref acquire path changed'
    menu = mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I')
    logi = mid(d, 'Landroid/util/Log;', 'i', '(Ljava/lang/String;Ljava/lang/String;)I')
    def blkE(p, na):
        a = Asm(p)
        a.const_string(4, sid(d, 'pref_upscale_key')); a.inv_static(menu, [4]); a.move_result(4)
        a.if_nez(4, na(338))                        # RES ON -> original key40 acquire
        a.const_string(0, sid(d, 'VIVO_GATE')); a.const_string(1, sid(d, 'pref_upscale_key'))
        a.inv_static(logi, [0, 1])
        a.ret_obj(13)                               # RES OFF: leave key40 untouched
        return a.done()
    insert(c, 338, blkE); check(c)
    return relocate(raw, {m: c.build()}), [m]


def rebuild_apk(src, dst, newdex):
    """Copy APK entries, replacing dex files; drop old v1 signature; 4-byte align STORED entries (16 KiB for .so)."""
    zi = zipfile.ZipFile(src)
    with open(src, 'rb') as f: blob = f.read()
    out = bytearray(); central = bytearray(); n = 0
    for info in zi.infolist():
        name = info.filename
        if name.startswith('META-INF/') and name.rsplit('.', 1)[-1] in ('SF', 'RSA', 'DSA', 'EC', 'MF'):
            continue
        lh = info.header_offset
        sig, ver, flag, meth, mt, md, crc, csz, usz, nl, el = struct.unpack_from('<IHHHHHIIIHH', blob, lh)
        assert sig == 0x04034b50
        fname = blob[lh + 30: lh + 30 + nl]
        dstart = lh + 30 + nl + el
        if name in newdex:
            data = newdex[name]
            import zlib
            co = zlib.compressobj(9, zlib.DEFLATED, -15); comp = co.compress(data) + co.flush()
            meth, crc, csz, usz = 8, zlib.crc32(data) & 0xffffffff, len(comp), len(data); payload = comp
        else:
            payload = blob[dstart:dstart + info.compress_size]
            crc, csz, usz = info.CRC, info.compress_size, info.file_size
        flag &= ~0x08  # sizes in local header
        off = len(out)
        extra = b''
        if meth == 0:
            align = 16384 if name.endswith('.so') else 4
            need = (-(off + 30 + nl)) % align
            if need and need < 4: need += align
            if need: extra = struct.pack('<HH', 0xd935, need - 4) + b'\0' * (need - 4)
        out += struct.pack('<IHHHHHIIIHH', 0x04034b50, ver, flag, meth, mt, md, crc, csz, usz, nl, len(extra)) + fname + extra + payload
        central += struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, info.create_version | (info.create_system << 8), ver, flag, meth, mt, md,
                               crc, csz, usz, nl, 0, 0, 0, 0, info.external_attr, off) + fname
        n += 1
    cd = len(out); out += central
    out += struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, n, n, len(central), cd, 0)
    open(dst, 'wb').write(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src)
    c1, m1 = patch_classes(z.read('classes.dex'))
    c2, m2 = patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p149a', 'wb').write(c1); open('classes2.dex.p149a', 'wb').write(c2)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
    print('classes2.dex', len(c2), hashlib.sha256(c2).hexdigest())
    print('APK', dst)
