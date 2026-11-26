#!/usr/bin/env python3
"""XENIUS P164B — P164 with the 50 MP frame cap 25 -> 20 (Llei clamp, one word).

P156L/P164 logs: up to 20 frames every captured 50 MP frame arrived; at 25 the vivo HAL stalls (130-265 ms frame
gaps) and drops frames (25 asked -> 21 delivered). Settings above 20 now shoot 20. Slots / maxImages stay 25.
Run: python3 build_p164b.py XENIUS_P164_UNSIGNED.apk XENIUS_P164B_20F_UNSIGNED.apk
"""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from build_p149a import one, rebuild_apk
from build_p149b import fix_hdr

P164_DEX = 'ced61237a83dbad4902e8de6764ab00430b90b1c8bb4eaee79a4933e085239ed'
CAP = 20

def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P164_DEX, 'classes.dex is not P164'
    open('/tmp/_p164b.dex', 'wb').write(raw); d = Dex('/tmp/_p164b.dex')
    m = one(d, 'Llei;', 'onCaptureCompleted'); (_, _, _, _), w = d.insns(m); w = list(w)
    assert w[475:477] == [0x0213, 25] and w[477] & 0xff == 0x36
    b = bytearray(raw); struct.pack_into('<H', b, d.code[m] + 16 + 2 * 476, CAP); fix_hdr(b)
    return bytes(b)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
