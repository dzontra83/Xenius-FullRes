#!/usr/bin/env python3
"""XENIUS P173 — crash fixes from the LMC crash log (LMC8.3/CRASH LOG/*.Prop, 2026-11-20), on P172.

1. Llei.onCaptureCompleted, 50 MP burst submit loop: CameraCaptureSession.capture() threw
   CameraAccessException CAMERA_ERROR (camera device in error / closing) -> app crash. The capture call is now inside a
   catch-all try; on exception the loop is abandoned (return-void) instead of killing the app.
2. Lldt.a (GCam image <-> request matcher): an image with no matching pending request left v2 == null and
   v2.getClass() threw NullPointerException -> crash. Now: if no match, close that image, monitor-exit, return.
3. Lgh.onSaveInstanceState (base of the app's activities): Activity state 'android:fragments' (~490 KB of settings
   fragments) exceeded the binder limit on onStop -> TransactionTooLargeException crash. After super, the
   'android:fragments' entry is removed from the Bundle (key built as "android:support:fragments"[0:8] + [16:]).
Run: python3 build_p173.py XENIUS_P172_UNSIGNED.apk XENIUS_P173_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code, insert, check, relocate
from build_p149a import one, mid, sid, rebuild_apk
from build_p149b import fix_hdr
from build_p163 import S
P172_DEX = '6f2fb5dab93b1f99279f4794ca690ca26aeb6c9320571a03953ffd388906cc58'

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P172_DEX, 'classes.dex is not P172'
    open('/tmp/_p173.dex', 'wb').write(raw); d = Dex('/tmp/_p173.dex')
    M = lambda c, n, p: mid(d, c, n, p)
    out = {}
    # 1 ---- Llei capture loop
    cap = M('Landroid/hardware/camera2/CameraCaptureSession;', 'capture',
            '(Landroid/hardware/camera2/CaptureRequest;Landroid/hardware/camera2/CameraCaptureSession$CaptureCallback;Landroid/os/Handler;)I')
    m = one(d, 'Llei;', 'onCaptureCompleted'); c = Code(raw, d.code[m])
    h = [i for i in range(len(c.w) - 7) if c.w[i:i + 3] == [0x406e, cap, 0x3175] and c.w[i + 3] & 0xff == 0xd8 and c.w[i + 5] & 0xff == 0x39
         and c.w[i + 7] == 0x000e]
    assert len(h) == 1, h
    pc = h[0]; ret = pc + 7                              # capture(3) add-int/lit8(2) if-nez(2) return-void
    assert not any(t[0] <= pc < t[0] + t[1] for t in c.tries)
    insert(c, ret, lambda base, na: [0x000e])           # handler: return-void (branches to old return land here too)
    c.tries.append([pc, 3, len(c.handlers)]); c.handlers.append([[], ret])
    c.tries.sort(key=lambda t: t[0]); check(c); out[m] = c.build()
    # 2 ---- Lldt.a null match
    m = [i for i, (cc, p, n) in enumerate(d.methods) if cc == 'Lldt;' and n == 'a' and i in d.code and d.mname(i).endswith('()V')]
    assert len(m) == 1; m = m[0]; c = Code(raw, d.code[m])
    gc = M('Ljava/lang/Object;', 'getClass', '()Ljava/lang/Class;')
    ldp = d.types.index('Lldp;')
    h = [i for i in range(len(c.w) - 5) if c.w[i:i + 3] == [0x106e, gc, 0x0002] and c.w[i + 3] == (0x22 | 5 << 8) and c.w[i + 4] == ldp]
    assert len(h) == 1, h
    close = M('Llju;', 'close', '()V')
    def B2(base, na):
        a = S(base)
        a.b21(0x39, 2, 'ok')                              # if-nez v2 -> ok
        a.inv(0x72, close, [3])                           # image.close()
        a.raw(0x001e | 17 << 8)                           # monitor-exit v17
        a.raw(0x000e)                                     # return-void
        a.L('ok')
        return a.done()
    insert(c, h[0], B2); check(c); out[m] = c.build()
    # 3 ---- Lgh.onSaveInstanceState
    m = [i for i, (cc, p, n) in enumerate(d.methods) if cc == 'Lgh;' and n == 'onSaveInstanceState' and i in d.code][0]
    c = Code(raw, d.code[m])
    sup = M('Landroid/app/Activity;', 'onSaveInstanceState', '(Landroid/os/Bundle;)V')
    h = [i for i in range(len(c.w) - 3) if c.w[i:i + 2] == [0x206f, sup]]
    assert len(h) == 1, h
    p = h[0] + 3
    assert c.w[p] == 0x000e
    sub2 = M('Ljava/lang/String;', 'substring', '(II)Ljava/lang/String;'); sub1 = M('Ljava/lang/String;', 'substring', '(I)Ljava/lang/String;')
    cat = M('Ljava/lang/String;', 'concat', '(Ljava/lang/String;)Ljava/lang/String;')
    rem = M('Landroid/os/Bundle;', 'remove', '(Ljava/lang/String;)V')
    def B3(base, na):
        a = S(base)
        a.b21(0x38, 4, 'end')
        a.cs(0, sid(d, 'android:support:fragments'))
        a.c4(1, 0); a.c16(2, 8); a.inv(0x6e, sub2, [0, 1, 2]); a.mro(1)
        a.c16(2, 16); a.inv(0x6e, sub1, [0, 2]); a.mro(0)
        a.inv(0x6e, cat, [1, 0]); a.mro(1)
        a.inv(0x6e, rem, [4, 1])
        a.L('end')
        return a.done()
    insert(c, p, B3); check(c); out[m] = c.build()
    o = bytearray(relocate(raw, out)); fix_hdr(o)
    return bytes(o)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
