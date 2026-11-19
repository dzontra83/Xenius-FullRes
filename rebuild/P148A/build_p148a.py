#!/usr/bin/env python3
"""XENIUS P148A — 50 MP HDR+ up to 10 frames, on top of P149B (RES 12/50 MP switch).

K13 frame flow (5 is a structural cap, not native):
  Llei.onCaptureCompleted  clamps pref_zsl_frames (per lens) to 2..5, issues N RAW50 captures
  Lleu.onImageAvailable    puts each 8192x6144 frame into one of 5 named System-property slots; 6th+ is closed
  Ldvm.p                   feeds slot1..slot5 into HdrPlusInterface.addPayloadFrame recursively; stops at an empty slot
P148A:
  L1 Llei   clamp 2..10 (invalid -> 5 as before)
  L2 Llei   at burst start remove+close stale frames from all 10 slots
  P1 Lleu   slots 6..10 before closing an overflow frame
  C1 Ldvm.p next-slot order extended to 10 frames
  C2 Ldvm.p before feeding frame 1 of a shot (worker thread only), wait up to 3 s for frame N to arrive
  R1 Llel.c / Llfe.e  RAW50 ImageReader maxImages 5 -> 10
"""
import sys, os, struct, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check
from build_p149a import Asm, one, mid, sid, rebuild_apk
import build_p149b as B

MAXF = 10
EXTRA = ['ShotLogData_base_frame_index_get', 'ShotLogData_base_frame_snr_get',
         'ShotLogData_base_frame_timestamp_ns_get', 'ShotLogData_capture_time_get',
         'ShotLogData_final_payload_frame_sharpness_get']          # slots 6..10 (strings unused by any code)
SLOT = ['getHardwareBuffer', 'getTimestamp', 'ShotLogData_merged_frame_snr_get',
        'ShotLogData_shasta_merged_frame_count_get', 'ShotLogData_merged_frame_count_get'] + EXTRA   # frame k -> SLOT[k-1]
MARKERS = ['new_RawWriteView__SWIG_1', 'getAHardwareBufferPtr']   # slot1 / slot2 occupancy markers


def const_int(a, v, n):
    if -8 <= n <= 7: a.w += [0x12 | v << 8 | (n & 15) << 12]
    else: a.w += [0x13 | v << 8, n & 0xffff]


def extra_methods(d, new):
    ids = dict(props=mid(d, 'Ljava/lang/System;', 'getProperties', ')Ljava/util/Properties;'),
               get=mid(d, 'Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               remove=mid(d, 'Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               iclose=mid(d, 'Landroid/media/Image;', 'close', '()V'),
               intValue=mid(d, 'Ljava/lang/Integer;', 'intValue', '()I'),
               myLooper=mid(d, 'Landroid/os/Looper;', 'myLooper', '()Landroid/os/Looper;'),
               mainLooper=mid(d, 'Landroid/os/Looper;', 'getMainLooper', '()Landroid/os/Looper;'),
               sleep=mid(d, 'Landroid/os/SystemClock;', 'sleep', '(J)V'),
               Image=d.types.index('Landroid/media/Image;'), Integer=d.types.index('Ljava/lang/Integer;'))
    for s in EXTRA:
        assert not d.xrefs_string(sid(d, s)), s

    # ---- Llei.onCaptureCompleted ----
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(d.b, d.code[m])
    assert c.w[79:93] == [0x003d, 13, 0x5212, 0x2036, 10, 0x2212, 0x2034, 4, 0x0029, 6, 0x2012, 0x0029, 3, 0x5012]
    # write L1 explicitly (if-gt v0,v2 -> cap ; goto 84 ; cap: move v0,v2 ; goto 93)
    def L1(p, na):
        a = Asm(p)
        const_int(a, 2, MAXF)
        a.fix.append((len(a.w), a.pc(), 'cap', '21t')); a.w += [0x0036 | (0 << 8) | (2 << 12), 0]  # if-gt v0, v2
        a.goto32(na(84))
        a.label('cap'); a.w += [0x0001 | (0 << 8) | (2 << 12)]                                      # move v0, v2
        a.goto32(na(93))
        return a.done()
    insert(c, 81, L1)
    assert c.w[8] == 0x001a
    def L2(p, na):   # at pc 8: v0,v2,v4,v6 free (v1 callback, v3 handler, v5 session, v7 request live)
        a = Asm(p)
        a.inv_static(ids['props'], []); a.move_result_obj(0)
        for i, key in enumerate(SLOT + MARKERS):
            a.const_string(2, sid(d, key)); a.inv_iface(ids['remove'], [0, 2]); a.move_result_obj(4)
            if key in MARKERS: continue
            a.w += [0x0020 | (6 << 8) | (4 << 12), ids['Image']]           # instance-of v6, v4, Image
            a.if_eqz(6, 'n%d' % i)
            a.check_cast(4, ids['Image']); a.inv_virtual(ids['iclose'], [4])
            a.label('n%d' % i)
        a.goto32(na(8))
        return a.done()
    insert(c, 8, L2); check(c); new[m] = c

    # ---- Lleu.onImageAvailable: overflow -> slots 6..10 ----
    m = one(d, 'Lleu;', 'onImageAvailable'); c = Code(d.b, d.code[m])
    assert c.w[927:930] == [0x106e, ids['iclose'], 0x0002], c.w[925:930]
    assert c.w[945] & 0xff == 0x72 and c.w[946] == mid(d, 'Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    def P1(p, na):   # v0 = props, v2 = image, v1/v4 scratch; put happens at old 945: put(v0, v1, v2)
        a = Asm(p)
        for i, key in enumerate(EXTRA):
            a.const_string(1, sid(d, key)); a.inv_iface(ids['get'], [0, 1]); a.move_result_obj(4)
            a.if_nez(4, 'f%d' % i); a.goto32(na(945)); a.label('f%d' % i)
        a.goto32(na(927))
        return a.done()
    insert(c, 927, P1); check(c); new[m] = c

    # ---- Ldvm.p ----
    m = one(d, 'Ldvm;', 'p'); c = Code(d.b, d.code[m])
    assert c.w[795] == 0x011a and c.w[807] & 0xff == 0x72
    def C1(p, na):   # v3 = index of frame just added; choose slot of the next frame into v1, then old 807
        a = Asm(p)
        const_int(a, 1, 3); a.fix.append((len(a.w), a.pc(), na(795), '22t')); a.w += [0x0032 | (3 << 8) | (1 << 12), 0]
        for k, key in enumerate(EXTRA, start=4):
            const_int(a, 1, k)
            a.fix.append((len(a.w), a.pc(), 'x%d' % k, '22t')); a.w += [0x0033 | (3 << 8) | (1 << 12), 0]   # if-ne v3,v1
            a.const_string(1, sid(d, key)); a.goto32(na(807)); a.label('x%d' % k)
        a.goto32(na(795))
        return a.done()
    assert c.w[357] == 0x2239, hex(c.w[357])          # if-nez v34
    def C2(p, na):   # pc 357: first 50 MP frame of a shot -> wait for frame N (worker thread only)
        a = Asm(p)
        a.w += [0x0039 | (31 << 8), 0]; a.fix.append((len(a.w) - 2, a.pc() - 2, 'out', '21t'))     # if-nez v31
        a.w += [0x0039 | (34 << 8), 0]; a.fix.append((len(a.w) - 2, a.pc() - 2, 'out', '21t'))     # if-nez v34
        a.inv_static(ids['myLooper'], []); a.move_result_obj(0)
        a.inv_static(ids['mainLooper'], []); a.move_result_obj(1)
        a.fix.append((len(a.w), a.pc(), 'out', '22t')); a.w += [0x0032 | (0 << 8) | (1 << 12), 0]    # if-eq v0,v1
        a.inv_static(ids['props'], []); a.move_result_obj(1)
        a.const_string(0, sid(d, 'pref_hdrnet_key')); a.inv_iface(ids['get'], [1, 0]); a.move_result_obj(0)
        a.w += [0x0020 | (2 << 8) | (0 << 12), ids['Integer']]; a.if_eqz(2, 'out')
        a.check_cast(0, ids['Integer']); a.inv_virtual(ids['intValue'], [0]); a.move_result(2)
        for k in range(2, MAXF + 1):
            const_int(a, 3, k)
            a.fix.append((len(a.w), a.pc(), 'k%d' % k, '22t')); a.w += [0x0033 | (2 << 8) | (3 << 12), 0]  # if-ne v2,v3
            a.const_string(0, sid(d, SLOT[k - 1])); a.goto32('wait'); a.label('k%d' % k)
        a.goto32('out')
        a.label('wait'); a.w += [0x0613, 300]                                       # const/16 v6, 300 (x10 ms)
        a.label('loop')
        a.inv_static(ids['props'], []); a.move_result_obj(1)
        a.inv_iface(ids['get'], [1, 0]); a.move_result_obj(1); a.if_nez(1, 'out')
        a.w += [0x0216, 10]                                                         # const-wide/16 v2, 10
        a.inv_static(ids['sleep'], [2, 3])
        a.w += [0x06d8, 0xff06]                                                     # add-int/lit8 v6, v6, -1
        a.fix.append((len(a.w), a.pc(), 'loop', '21t')); a.w += [0x063c, 0]          # if-gtz v6, loop
        a.label('out'); a.goto32(na(357))
        return a.done()
    insert(c, 795, C1)
    insert(c, 357, C2); check(c); new[m] = c

    # ---- R1: maxImages 5 -> 10 (words inside already-collected Llel.c / Llfe.e) ----
    for cls, n, orig in (('Llel;', 'c', [0x0c13, 5]), ('Llfe;', 'e', [0x0813, 5])):
        cc = new[one(d, cls, n)]
        hits = [i for i in range(len(cc.w) - 1) if cc.w[i:i + 2] == orig and cc.w[i - 2:i] in ([0x0b13, 32], [0x0713, 32])]
        assert len(hits) == 1, (cls, hits)
        cc.w[hits[0] + 1] = MAXF


# Asm: support 22t fixups too
_done = Asm.done
def _done22(self):
    for i, src, t, f in list(self.fix):
        if f == '22t':
            dst = self.lab[t] if isinstance(t, str) else t; off = dst - src
            assert -32768 <= off < 32768; self.w[i + 1] = off & 0xffff
    self.fix = [x for x in self.fix if x[3] != '22t']
    return _done(self)
Asm.done = _done22


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    extra_methods(d, new)
    c1 = B.finalize_classes(raw1, d, new)
    c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p148a', 'wb').write(c1); open('classes2.dex.p148a', 'wb').write(c2)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
    print('classes2.dex', len(c2), hashlib.sha256(c2).hexdigest())
