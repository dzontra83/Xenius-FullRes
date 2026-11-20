#!/usr/bin/env python3
"""XENIUS P158 — steady lens during the 50 MP burst, on top of P157 (classes2.dex unchanged).

The 50 MP burst request is a fresh STILL_CAPTURE template; before P158 only ISO/exposure were copied from the
preview. Focus and OIS started from template defaults, so the lens/OIS could re-settle right as the burst began.
In Llei.onCaptureCompleted (the RAW50 trigger):
  L1 at the trigger (pc 847, v7 = trigger preview result): store the result's LENS_FOCUS_DISTANCE and
     LENS_OPTICAL_STABILIZATION_MODE in System properties (removed first, so a missing value never goes stale).
  L2 just before build() (pc 1298): if a focus distance was stored -> CONTROL_AF_MODE = OFF + LENS_FOCUS_DISTANCE =
     that value (focus locked where the preview was); if an OIS mode was stored -> same LENS_OPTICAL_STABILIZATION_MODE.

Run: python3 build_p158.py XENIUS_P157_STREAM15_UNSIGNED.apk XENIUS_P158_STEADY_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p157 import A

P157_DEX = 'b6926409f7065c89e8f29c7bdc86cd8fdc23b178eab6cedf75dd67b129a982e9'
CR, CQ = 'Landroid/hardware/camera2/CaptureResult;', 'Landroid/hardware/camera2/CaptureRequest;'


def fid(d, cls, name):
    r = [i for i, f in enumerate(d.fields) if f[0] == cls and f[2] == name]; assert len(r) == 1; return r[0]


def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P157_DEX, 'classes.dex is not P157'
    open('/tmp/_p158.dex', 'wb').write(raw); d = Dex('/tmp/_p158.dex')
    MAP = 'Ljava/util/Map;'
    get = mid(d, MAP, 'get', '(Ljava/lang/Object;)Ljava/lang/Object;')
    rem = mid(d, MAP, 'remove', '(Ljava/lang/Object;)Ljava/lang/Object;')
    put = mid(d, MAP, 'put', '(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;')
    props = mid(d, 'Ljava/lang/System;', 'getProperties', '()Ljava/util/Properties;')
    rget = mid(d, CR, 'get', '(Landroid/hardware/camera2/CaptureResult$Key;)Ljava/lang/Object;')
    bset = mid(d, 'Landroid/hardware/camera2/CaptureRequest$Builder;', 'set',
               '(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V')
    build = mid(d, 'Landroid/hardware/camera2/CaptureRequest$Builder;', 'build', ')Landroid/hardware/camera2/CaptureRequest;')
    valueOf = mid(d, 'Ljava/lang/Integer;', 'valueOf', '(I)Ljava/lang/Integer;')
    getdev = mid(d, 'Landroid/hardware/camera2/CameraCaptureSession;', 'getDevice', ')Landroid/hardware/camera2/CameraDevice;')
    KFD, KOIS = sid(d, 'LENS_FOCUS_DISTANCE'), sid(d, 'LENS_OPTICAL_STABILIZATION_MODE')
    pairs = [(KFD, 'LENS_FOCUS_DISTANCE'), (KOIS, 'LENS_OPTICAL_STABILIZATION_MODE')]

    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m]); w = c.w
    assert w[1298:1301] == [0x106e, build, 0x0007] and w[1301] == 0x070c, [hex(x) for x in w[1298:1302]]
    assert w[936:939] == [0x106e, getdev, 0x0005] and w[924] & 0xff == 0x38 and w[932] == 0x2407  # move-object v4,v2

    def L2(p, na):   # v0..v3 free; v7 = Builder
        a = A(p)
        a.inv(0x71, props, []); a.mresobj(0)
        a.cstr(1, KFD); a.inv(0x72, get, [0, 1]); a.mresobj(2); a.br(0x38, 2, 'nofd')
        a.w += [0x0162, fid(d, CQ, 'LENS_FOCUS_DISTANCE')]; a.inv(0x6e, bset, [7, 1, 2])
        a.w += [0x0162, fid(d, CQ, 'CONTROL_AF_MODE'), 0x0212]                  # sget v1 ; const/4 v2, 0
        a.inv(0x71, valueOf, [2]); a.mresobj(2); a.inv(0x6e, bset, [7, 1, 2])
        a.label('nofd')
        a.cstr(1, KOIS); a.inv(0x72, get, [0, 1]); a.mresobj(2); a.br(0x38, 2, 'noois')
        a.w += [0x0162, fid(d, CQ, 'LENS_OPTICAL_STABILIZATION_MODE')]; a.inv(0x6e, bset, [7, 1, 2])
        a.label('noois')
        return a.done()
    insert(c, 1298, L2)

    def L1(p, na):   # v0 = props, v7 = preview TotalCaptureResult, v1/v2 scratch
        a = A(p)
        a.inv(0x71, props, []); a.mresobj(0)
        for k, (s, name) in enumerate(pairs):
            a.cstr(1, s); a.inv(0x72, rem, [0, 1])
            a.w += [0x0262, fid(d, CR, name)]; a.inv(0x6e, rget, [7, 2]); a.mresobj(2)   # sget v2 key ; get
            a.br(0x38, 2, 'n%d' % k); a.inv(0x72, put, [0, 1, 2]); a.label('n%d' % k)
        return a.done()
    assert w[847] == 0x0162 and w[849:851] == [0x206e, rget]   # sget v1 SENSOR_SENSITIVITY ; get {v7,v1}
    insert(c, 847, L1)   # v7 is still the result here (later move-result-wide v6 clobbers v7 on the ISO-cap path)
    check(c)

    out = bytearray(relocate(raw, {m: c.build()})); fix_hdr(out)
    return bytes(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
