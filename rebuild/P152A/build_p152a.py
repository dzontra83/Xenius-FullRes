#!/usr/bin/env python3
"""XENIUS P152A — P148D + real 50 MP frames for every slot + capture-result leak fix.

F1 Lleu.onImageAvailable: K13 closed every new frame unless it sat in slot 1 or 2, so frames in slots 3..10 were
   closed before HDR+ read them ('Image is already closed' in Ldvm.p). The consumer then re-added the previous
   frame -> duplicate frames, identical timestamps ('0.0 ms gap'), missing gyro/sharpness. Now a frame stored in
   ANY slot is kept open until HDR+ consumes it.
F2 Llei.onCaptureCompleted: after the first 50 MP shot every capture result (preview 30 fps) was stored in System
   properties ('onCaptureCompleted<ts>') and never removed. Now only results of the listener-less burst callback
   with CONTROL_CAPTURE_INTENT == STILL_CAPTURE are stored (exactly the 50 MP frames the consumer looks up).
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dexpatch import Code, insert, check
from build_p149a import Asm, one, mid, sid, rebuild_apk
import build_p149b as B, build_p148a as A, build_p148b as K, build_p148c as C, build_p148d as D


def p152_methods(d, new):
    props = mid(d, 'Ljava/lang/System;', 'getProperties', ')Ljava/util/Properties;')
    get = mid(d, 'Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    # F1
    c = new[one(d, 'Lleu;', 'onImageAvailable')]
    assert c.w[654:658] == [0x2032, 5, 0x106e, mid(d, 'Landroid/media/Image;', 'close', '()V')], c.w[654:658]
    def F1(p, na):
        a = Asm(p)
        a.inv_static(props, []); a.move_result_obj(0)
        for key in A.SLOT[2:]:
            a.const_string(1, sid(d, key)); a.inv_iface(get, [0, 1]); a.move_result_obj(1)
            a.fix.append((len(a.w), a.pc(), na(659), '22t')); a.w += [0x0032 | (1 << 8) | (2 << 12), 0]   # if-eq v1, v2 -> keep
        return a.done()                                      # not in any slot -> original close at 656
    insert(c, 656, F1); check(c)
    # F2
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = new[m]
    f_a = d.fields.index(('Llei;', 'Lldg;', 'a'))
    intent = d.fields.index(('Landroid/hardware/camera2/CaptureRequest;', 'Landroid/hardware/camera2/CaptureRequest$Key;', 'CONTROL_CAPTURE_INTENT'))
    rget = mid(d, 'Landroid/hardware/camera2/CaptureRequest;', 'get', '(Landroid/hardware/camera2/CaptureRequest$Key;)Ljava/lang/Object;')
    intValue = mid(d, 'Ljava/lang/Integer;', 'intValue', '()I'); Integer = d.types.index('Ljava/lang/Integer;')
    ts = d.fields.index(('Landroid/hardware/camera2/CaptureResult;', 'Landroid/hardware/camera2/CaptureResult$Key;', 'SENSOR_TIMESTAMP'))
    # locate the store block: 'if-eq v6, v1 -> X' followed by sget-object v1, SENSOR_TIMESTAMP
    p = [i for i in range(len(c.w) - 4) if c.w[i] == 0x1632 and c.w[i + 2] == 0x0162 and c.w[i + 3] == ts]
    assert len(p) == 1, p
    p = p[0]; skip = p + (c.w[p + 1] - 0x10000 if c.w[p + 1] & 0x8000 else c.w[p + 1])
    def F2(q, na):
        a = Asm(q)
        a.w += [0x0154 | (4 << 12), f_a]                      # iget-object v1, v4, Llei;->a
        a.if_nez(1, na(skip))                                 # GCam listener callback -> don't store
        a.w += [0x0162, intent]; a.invoke(0x6e, rget, [6, 1]); a.move_result_obj(1)   # v1 = request.get(CONTROL_CAPTURE_INTENT)
        a.if_eqz(1, na(skip))
        a.check_cast(1, Integer); a.inv_virtual(intValue, [1]); a.move_result(1)
        a.w += [0x2212]                                       # const/4 v2, 2 (STILL_CAPTURE)
        a.fix.append((len(a.w), a.pc(), na(skip), '22t')); a.w += [0x0033 | (1 << 8) | (2 << 12), 0]   # if-ne v1,v2
        return a.done()
    insert(c, p + 2, F2); check(c)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.extra_methods(d, new); K.key40_methods(d, new); C.metadata_guards(d, new); D.d_methods(d, new); p152_methods(d, new)
    c1 = B.finalize_classes(raw1, d, new); c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p152a', 'wb').write(c1)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
