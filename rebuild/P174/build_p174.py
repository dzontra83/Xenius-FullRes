#!/usr/bin/env python3
"""XENIUS P174 = P173 + EXIF frame-count wait cap 3 s -> 1 s (Llpy.j loop: const/16 v0,150 -> 50; 20 ms steps)."""
import sys, os, zipfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from dexpatch import Code
from build_p149a import one, rebuild_apk
from build_p149b import fix_hdr
P173 = 'c3613921de7a80198c776f3a0df56b667364525033250111fb20a32b1b799512'
def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P173, 'not P173'
    open('/tmp/_p174.dex','wb').write(raw); d = Dex('/tmp/_p174.dex')
    m = one(d, 'Llpy;', 'j'); c = Code(raw, d.code[m])
    pos = [i for i in range(min(60, len(c.w)-1)) if c.w[i:i+2] == [0x0013, 150]]
    assert len(pos) == 1, pos
    off = d.code[m] + 16 + 2*pos[0] + 2
    o = bytearray(raw); assert o[off:off+2] == (150).to_bytes(2,'little')
    o[off:off+2] = (50).to_bytes(2,'little'); fix_hdr(o); return bytes(o)
if __name__ == '__main__':
    src, dst = sys.argv[1:3]; new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
