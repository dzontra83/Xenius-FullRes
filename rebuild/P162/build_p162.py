#!/usr/bin/env python3
"""XENIUS P162 — gyro for HDR+ (Llgn DirectGyro -> Llgw SensorEventListener gyro). Base: P160 or P161E (diag).

Diag (P161E): GCam's HdrPlusSession gyro provider is absent on every frame (12 MP and 50 MP). GCam's gyro factory
(Llgr) is Llgn "DirectGyro": SensorDirectChannel on a HardwareBuffer. vivo's gyro has no direct channel, so the
session comes back null ("Hardware was null") and HDR+ gets no gyro at all. GCam also ships Llgw: the same factory
interface built on a normal SensorEventListener (SENSOR_DELAY_FASTEST). Camera timestamps are BOOTTIME (diag:
frame ts ~ elapsedRealtimeNanos - 50..80 ms), the same clock as SensorEvent timestamps, so no offset is needed.
Change (in place, Lkyg.get provider case): new Llgn(SensorManager, Lkrr) -> new Llgw(SensorManager).

Run: python3 build_p162.py <P160 or P161E apk> <out apk>
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from build_p149a import one, mid, rebuild_apk
from build_p149b import fix_hdr

BASES = {'30d9336bbd86e082c1b9adaf850362878e65fb7d93aa1bb1aff572173278efcf': 'P160',
         'a9386a6b83ffbfa1c8e65abc31f4df2bfdde8b7dd62786f963b00e07b6ed561c': 'P161E'}

def patch(raw):
    h = hashlib.sha256(raw).hexdigest(); assert h in BASES, 'base must be P160 or P161E'
    open('/tmp/_p162.dex', 'wb').write(raw); d = Dex('/tmp/_p162.dex')
    gn, gw = d.types.index('Llgn;'), d.types.index('Llgw;')
    init_n = mid(d, 'Llgn;', '<init>', '(Landroid/hardware/SensorManager;Lkrr;)V')
    init_w = mid(d, 'Llgw;', '<init>', '(Landroid/hardware/SensorManager;)V')
    m = one(d, 'Lkyg;', 'get'); (_, _, _, _), w = d.insns(m); w = list(w)
    hits = [i for i in range(len(w) - 4) if w[i:i + 2] == [0x0222, gn] and w[i + 2:i + 5] == [0x3070, init_n, 0x0102]]
    assert len(hits) == 1, hits
    p = hits[0]; base = d.code[m] + 16
    b = bytearray(raw)
    struct.pack_into('<5H', b, base + 2 * p, 0x0222, gw, 0x2070, init_w, 0x0002)   # new-instance v2 Llgw ; invoke-direct {v2,v0}
    fix_hdr(b)
    print(BASES[h], '-> Lkyg.get pc', p, ': Llgn(SensorManager,Lkrr) -> Llgw(SensorManager)')
    return bytes(b)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
