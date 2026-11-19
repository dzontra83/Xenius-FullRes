#!/usr/bin/env python3
"""XENIUS P148B — P148A (10-frame 50 MP HDR+) + P149B (RES 12/50) + key40 held for the foreground session.

Problem: K2/K13 release key40 (setValue 40,0) on EVERY Lksn.onClosed. GCam also closes/reopens the camera while
the app stays open (lens/mode switches, session rebuilds, alternate Larb open path without acquire). A late
onClosed then leaves key40=0 and 50 MP silently stops until something (e.g. RawR) sets it again.

RawR rule (VendorCameraGate): hold the gate while the full-size camera is in use; release when done.
  K1 CameraActivity.onResume  put System property RESOLUTION_SWITCH (foreground mark)
  K2 Lksn.onClosed            RES ON and mark present -> skip release (RAW50 reader cleanup still runs)
  K3 CameraActivity.onStop    remove mark; RES ON -> release key40 (same call onClosed used)
  K4 Llel.c / Llfe.e          RES ON -> getC2apiPref(null) acquire right before the 50 MP session is configured
                              (no write when key40 already reads 1)
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, branches
from build_p149a import Asm, one, mid, sid, rebuild_apk
import build_p149b as B
import build_p148a as A   # also installs the 22t-aware Asm.done

CA = 'Lcom/google/android/apps/camera/legacy/app/activity/main/CameraActivity;'
MARK = 'RESOLUTION_SWITCH'


def key40_methods(d, new):
    ids = dict(props=mid(d, 'Ljava/lang/System;', 'getProperties', ')Ljava/util/Properties;'),
               get=mid(d, 'Ljava/util/Map;', 'get', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               put=mid(d, 'Ljava/util/Map;', 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;'),
               remove=mid(d, 'Ljava/util/Map;', 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;'),
               menu=mid(d, 'LMC/pref;', 'MenuValue', '(Ljava/lang/String;)I'),
               logi=mid(d, 'Landroid/util/Log;', 'i', '(Ljava/lang/String;Ljava/lang/String;)I'),
               gate=mid(d, 'LMC/c2a;', 'getC2apiPref', '(Lleo;)Lleo;'),
               leo_init=mid(d, 'Lleo;', '<init>', '(Landroid/hardware/camera2/CaptureRequest$Builder;)V'),
               Leo=d.types.index('Lleo;'))
    s_res, s_mark = sid(d, 'pref_upscale_key'), sid(d, MARK)

    # K1 onResume: after the existing log (pc 7), put mark.  regs=4: v0..v2 locals, v3 this.
    m = one(d, CA, 'onResume'); c = Code(d.b, d.code[m])
    assert c.w[7] == 0x0012 and c.outs >= 3
    def K1(p, na):
        a = Asm(p)
        a.inv_static(ids['props'], []); a.move_result_obj(0)
        a.const_string(1, s_mark); a.const_string(2, sid(d, 'onResume'))
        a.inv_iface(ids['put'], [0, 1, 2])
        return a.done()
    insert(c, 7, K1); check(c); new[m] = c

    # K3 onStop: before invoke-super (pc 7).  regs=3: v0,v1 locals, v2 this.
    m = one(d, CA, 'onStop'); c = Code(d.b, d.code[m])
    assert c.w[7] & 0xff == 0x6f and c.outs >= 2
    def K3(p, na):
        a = Asm(p)
        a.inv_static(ids['props'], []); a.move_result_obj(0)
        a.const_string(1, s_mark); a.inv_iface(ids['remove'], [0, 1])
        a.const_string(0, s_res); a.inv_static(ids['menu'], [0]); a.move_result(0)
        a.if_eqz(0, 'end')
        a.w += [0x0022, ids['Leo']]                         # new-instance v0, Lleo
        a.w += [0x0112]                                      # const/4 v1, 0
        a.invoke(0x70, ids['leo_init'], [0, 1])              # invoke-direct Lleo.<init>(null)
        a.inv_static(ids['gate'], [0])                       # release key40 (field a == null -> release path)
        a.label('end')
        return a.done()
    insert(c, 7, K3); check(c); new[m] = c

    # K2 Lksn.onClosed: before the release (pc 26 new-instance Lleo).  v0, v2 free here; continue at pc 36.
    m = one(d, 'Lksn;', 'onClosed'); c = Code(d.b, d.code[m])
    assert c.w[26] == 0x0022 and c.w[27] == ids['Leo'] and c.w[32] & 0xff == 0x71 and c.w[33] == ids['gate']
    def K2(p, na):
        a = Asm(p)
        a.const_string(0, s_res); a.inv_static(ids['menu'], [0]); a.move_result(0)
        a.if_eqz(0, na(26))                                  # RES OFF -> release as before
        a.inv_static(ids['props'], []); a.move_result_obj(0)
        a.const_string(2, s_mark); a.inv_iface(ids['get'], [0, 2]); a.move_result_obj(0)
        a.if_eqz(0, na(26))                                  # app not in foreground -> release
        a.const_string(0, s_mark); a.const_string(2, sid(d, 'onClosed')); a.inv_static(ids['logi'], [0, 2])
        a.goto32(na(36))                                     # keep key40, continue with RAW50 reader cleanup
        return a.done()
    insert(c, 26, K2); check(c); new[m] = c

    # K4: RES ON branch of the P149B session gates -> acquire before configuring the 50 MP session
    for cls, n, reg in (('Llel;', 'c', 13), ('Llfe;', 'e', 5)):
        c = new[one(d, cls, n)]
        br, _ = branches(c.w)
        tgt = [t for pc, f, t in br if f == '21t' and (c.w[pc] & 0xff) == 0x39 and (c.w[pc] >> 8) == reg][0]  # if-nez vRES
        def K4(p, na, reg=reg):
            a = Asm(p)
            a.w += [0x0012 | reg << 8]                        # const/4 vreg, 0
            a.inv_static(ids['gate'], [reg])                 # getC2apiPref(null) = acquire (RES ON)
            return a.done()
        insert(c, tgt, K4); check(c)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src); raw1 = z.read('classes.dex')
    d, new = B.collect_classes(raw1)
    A.extra_methods(d, new)
    key40_methods(d, new)
    c1 = B.finalize_classes(raw1, d, new)
    c2 = B.patch_classes2(z.read('classes2.dex'))
    open('classes.dex.p148b', 'wb').write(c1); open('classes2.dex.p148b', 'wb').write(c2)
    rebuild_apk(src, dst, {'classes.dex': c1, 'classes2.dex': c2})
    print('classes.dex', len(c1), hashlib.sha256(c1).hexdigest())
    print('classes2.dex', len(c2), hashlib.sha256(c2).hexdigest())
