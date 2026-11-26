#!/usr/bin/env python3
"""XENIUS P154 — quiet build on top of P153B (25-frame 50 MP HDR+).

Removes every debug side effect the 50 MP probe code still had, without changing behaviour:
  T  Lleu.onImageAvailable: the two "RAW50_REQ:applied / rejected" Toast.show() calls -> nop
  M  Lleu.onImageAvailable: ContentResolver.insert(...) of Download/RAW50_C_PROBE1.txt -> null
     (so the MediaStore probe file is never created; Ldvm.n/.t then skip their writes, uri == null)
  D  Lleu.onImageAvailable: the exception fallback that dumped a full ~100 MB DNG of the frame into
     Android/data/<pkg>/files/RAW50_REQ*.dng is skipped (existing 'rejected' edge)
  W  Llei / Lleu / Ldvm / Ldux: all FileWriter / PrintWriter / FileOutputStream construction, write, println,
     close -> nop (Download/RAW50_C_PROBE1*.txt and the private Android/data/.../RAW50_REQ, FrameNumber, Gcam_GetNumCameras logs)
All patches are in-place word replacements (same code length): no branch, try or layout changes.
System-property bookkeeping (frame slots, per-frame metadata) is untouched.

Run: python3 build_p154.py XENIUS_P153B_SPEED_25F_UNSIGNED.apk XENIUS_P154_QUIET_UNSIGNED.apk
"""
import sys, os, struct, zipfile, hashlib, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex, FMT, LEN
from build_p149a import rebuild_apk

P153B_DEX_SHA = '0f76e0bead2ec6da05ed9b41317cb90a8de8495a75daeba2a8e5adf902bd7e55'
CLASSES = ('Llei;', 'Lleu;', 'Ldvm;', 'Ldux;')
IO = ('Ljava/io/FileWriter;', 'Ljava/io/PrintWriter;', 'Ljava/io/FileOutputStream;')
IO_CALL_CLASSES = IO + ('Ljava/io/OutputStream;', 'Ljava/io/Writer;')
IO_CALLS = {'<init>', 'write', 'println', 'print', 'close', 'flush'}


def walk(w):
    pc = 0
    while pc < len(w):
        x = w[pc]; o = x & 0xff
        if o == 0 and x in (0x100, 0x200, 0x300):
            if x == 0x100: ln = 4 + w[pc + 1] * 2
            elif x == 0x200: ln = 2 + w[pc + 1] * 4
            else: ln = 4 + (w[pc + 1] * (w[pc + 2] | w[pc + 3] << 16) + 1) // 2
            pc += ln; continue
        ln = LEN[FMT[o]]; yield pc, o, ln; pc += ln


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P153B_DEX_SHA, 'classes.dex is not P153B'
    d = Dex.__new__(Dex)
    tmp = '/tmp/_p154.dex'; open(tmp, 'wb').write(raw); d = Dex(tmp)
    b = bytearray(raw)
    tid = {t: i for i, t in enumerate(d.types)}
    io_types = {tid[t] for t in IO if t in tid}
    stats = {'T': 0, 'M': 0, 'W_new': 0, 'W_call': 0}
    regs_nulled = []
    for mi, co in d.code.items():
        cls, _, name = d.methods[mi]
        if cls not in CLASSES: continue
        (_, _, _, _), w = d.insns(mi)
        base = co + 16
        def put(pc, words):
            for i, x in enumerate(words): struct.pack_into('<H', b, base + 2 * (pc + i), x)
        for pc, o, ln in walk(w):
            if o == 0x22 and w[pc + 1] in io_types:                      # new-instance vA, IO type
                put(pc, [0, 0]); stats['W_new'] += 1; regs_nulled.append((d.mname(mi), pc, (w[pc] >> 8)))
            elif 0x6e <= o <= 0x72:                                       # invoke-*
                mc, _, mn = d.methods[w[pc + 1]]
                if mc in IO_CALL_CLASSES and mn in IO_CALLS:
                    put(pc, [0, 0, 0]); stats['W_call'] += 1
                elif mc == 'Landroid/widget/Toast;' and mn == 'show' and cls == 'Lleu;':
                    put(pc, [0, 0, 0]); stats['T'] += 1
                elif mc == 'Landroid/content/ContentResolver;' and mn == 'insert' and cls == 'Lleu;':
                    nxt = w[pc + 3]
                    assert nxt & 0xff == 0x0c, 'insert not followed by move-result-object'
                    va = nxt >> 8; assert va < 16
                    put(pc, [0x12 | (va << 8), 0, 0, 0])               # const/4 vA, 0 ; nop x3
                    stats['M'] += 1
            elif 0x74 <= o <= 0x78:                                       # invoke-*/range
                mc, _, mn = d.methods[w[pc + 1]]
                if mc in IO_CALL_CLASSES and mn in IO_CALLS:
                    put(pc, [0, 0, 0]); stats['W_call'] += 1
        if cls == 'Lleu;' and name == 'onImageAvailable':
            # D  fallback path (reached only from exception handlers) dumps the whole 8192x6144 frame as a
            #    ~100 MB DNG into Android/data/<pkg>/files/RAW50_REQ*.dng and toasts "applied".
            #    `if-ne v0, v1, ->201` (buffer size == 100663296) becomes `goto/16 ->201` (the existing
            #    'rejected' edge), so the dump is never written.
            pc = 67
            assert w[pc] & 0xff == 0x33 and pc + (w[pc + 1] - 0x10000 if w[pc + 1] & 0x8000 else w[pc + 1]) == 201, 'leu 67'
            put(pc, [0x29, w[pc + 1]]); stats['D'] = 1
    print('patched:', stats)
    assert stats.get('D') == 1 and stats['T'] == 2 and stats['M'] == 1 and stats['W_new'] > 10 and stats['W_call'] > 50, stats
    # header checksums: SHA-1 signature (0x0c..0x20) over [0x20:], Adler32 (0x08) over [0x0c:]
    b[12:32] = hashlib.sha1(bytes(b[32:])).digest()
    struct.pack_into('<I', b, 8, zlib.adler32(bytes(b[12:])) & 0xffffffff)
    return bytes(b), regs_nulled


def verify_no_reads(raw_new, regs_nulled):
    """Sanity: after a removed new-instance vA, vA must not be read by any surviving instruction before it is
    redefined (straight-line scan up to 400 code units)."""
    tmp = '/tmp/_p154n.dex'; open(tmp, 'wb').write(raw_new); d = Dex(tmp)
    by = {}
    for mi in d.code: by[d.mname(mi)] = mi
    bad = []
    for mname, pc0, r in regs_nulled:
        lines = d.dis(by[mname]).split('\n')[1:]
        for l in lines:
            pc = int(l.split(':')[0])
            if pc <= pc0 or pc > pc0 + 400: continue
            ins = l.split(':', 1)[1].strip()
            if ins.startswith('nop'): continue
            op, _, args = ins.partition(' ')
            regs = [a.strip('{},') for a in args.split(',')]
            vr = 'v%d' % r
            if not regs or vr not in [x.split(' ')[0] for x in regs]: continue
            first = regs[0].split(' ')[0]
            writes_first = op.startswith(('const', 'move', 'new-', 'iget', 'sget', 'aget'))
            if first == vr and writes_first and not op.startswith('check-cast'): break   # redefined
            bad.append((mname[:60], pc0, pc, ins[:90])); break
    return bad


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    raw = zipfile.ZipFile(src).read('classes.dex')
    new, nulled = patch(raw)
    bad = verify_no_reads(new, nulled)
    for x in bad: print('READ AFTER REMOVED new-instance:', x)
    assert not bad
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest())
    print('wrote', dst)
