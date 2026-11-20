#!/usr/bin/env python3
"""XENIUS P156 — faster 50 MP burst start, on top of P155.

Llei.onCaptureCompleted (the RAW50 trigger: first preview result after the shutter press) called
`session.stopRepeating()` before queuing the 50 MP captures. P156 calls `session.abortCaptures()` instead:
the queued/in-flight preview requests are flushed (abortCaptures also clears the repeating request), so the
50 MP frames don't wait behind them. Latency Lab P37 on ID 5: stopRepeating ~355 ms, flush ~250 ms to the first
50 MP exposure (2 of 3 runs). The preview is restored by the existing code right after the captures are queued.
One word changed (method index of the same ()V invoke). classes2.dex unchanged from P155.

Run: python3 build_p156.py XENIUS_P155_KEY40_UNSIGNED.apk XENIUS_P156_FLUSH_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from build_p149a import rebuild_apk, one, mid

P154B_DEX = 'b3482bcab02c1073aae6954db17e3d6888dbf25a52dbd814a1e0949116f0cbca'

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P154B_DEX, 'classes.dex is not P154B/P155'
    open('/tmp/_p156.dex', 'wb').write(raw); d = Dex('/tmp/_p156.dex')
    m = one(d, 'Llei;', 'onCaptureCompleted')
    stop = mid(d, 'Landroid/hardware/camera2/CameraCaptureSession;', 'stopRepeating', '()V')
    abort = mid(d, 'Landroid/hardware/camera2/CameraCaptureSession;', 'abortCaptures', '()V')
    (_, _, _, _), w = d.insns(m)
    hits = [pc for pc in range(len(w) - 2) if w[pc] == 0x106e and w[pc + 1] == stop and w[pc + 2] == 0x0005]
    assert len(hits) == 1, hits
    b = bytearray(raw)
    struct.pack_into('<H', b, d.code[m] + 16 + 2 * (hits[0] + 1), abort)
    b[12:32] = hashlib.sha1(bytes(b[32:])).digest()
    struct.pack_into('<I', b, 8, zlib.adler32(bytes(b[12:])) & 0xffffffff)
    print('Llei.onCaptureCompleted pc', hits[0], ': stopRepeating -> abortCaptures')
    return bytes(b)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
