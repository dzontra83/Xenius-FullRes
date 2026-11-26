#!/usr/bin/env python3
"""XENIUS P162B — open the HDR+ gyro gate. Base: P162 (or P162D diag).

P162D diag: gyro provider still absent. Lied.get (provider of Optional<Llgr> for HdrPlusSession) only returns the
gyro factory if: device-flag Lliy.d && a gyro sensor exists && sensor.isDirectChannelTypeSupported(HARDWARE_BUFFER)
&& highest direct report rate >= FAST && ReadHardwareBufferJniFunctions.isSupported(). vivo has no direct channel.
Since P162 the factory is the normal SensorEventListener gyro (Llgw), so the direct-channel checks don't apply:
  pc 25  if-eqz Lliy.d -> nop nop         (flag check skipped)
  pc 34  const/4 v1,2  -> goto pc 53      (direct-channel / rate / JNI checks skipped)
Kept: gyro sensor must exist (pc 28-32). In place, 3 words.

Run: python3 build_p162b.py <P162 or P162D apk> <out apk>
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from build_p149a import one, rebuild_apk
from build_p149b import fix_hdr

BASES = {'880a7e4b83f34d1b83a6c8fa04a1648bfe2fae99c8ba95006dff27eb72ae3481': 'P162',
         '961363ac98e916218fdbc5d3c57d18f5f3731577addcfa4d0e389a934f7ad8b0': 'P162D'}

def patch(raw):
    h = hashlib.sha256(raw).hexdigest(); assert h in BASES, 'base must be P162 or P162D'
    open('/tmp/_p162b.dex', 'wb').write(raw); d = Dex('/tmp/_p162b.dex')
    m = one(d, 'Lied;', 'get'); (_, _, _, _), w = d.insns(m); w = list(w)
    fd = [i for i, f in enumerate(d.fields) if f == ('Lliy;', 'Z', 'd')][0]
    assert w[23:25] == [0x1155, fd] and w[25] & 0xff == 0x38 and (w[25] >> 8) == 1, [hex(x) for x in w[23:27]]
    assert w[34] == 0x2112 and w[53] & 0xff == 0x72, (hex(w[34]), hex(w[53]))          # const/4 v1,2 ; invoke-interface (pii.get)
    base = d.code[m] + 16; b = bytearray(raw)
    struct.pack_into('<2H', b, base + 2 * 25, 0, 0)
    struct.pack_into('<H', b, base + 2 * 34, 0x28 | ((53 - 34) << 8))                     # goto +19
    fix_hdr(b); print(BASES[h], '-> Lied.get gyro gate opened')
    return bytes(b)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
