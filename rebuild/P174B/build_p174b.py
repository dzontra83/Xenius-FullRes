#!/usr/bin/env python3
"""XENIUS P174B = P174 + fix: Lgh.onSaveInstanceState outs_size 2 -> 3 (P173's substring(II) needs 3 args; VerifyError on start)."""
import sys, os, zipfile, hashlib, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dex import Dex
from build_p149a import rebuild_apk
from build_p149b import fix_hdr
P174 = 'ab177e574061b0f6ba92c8c4c39e6b7496ebd2336e82b86af69a281fd0214d9b'
def patch(raw):
    assert hashlib.sha256(raw).hexdigest() == P174, 'not P174'
    open('/tmp/_p174b.dex','wb').write(raw); d = Dex('/tmp/_p174b.dex')
    m = [i for i,(c,p,n) in enumerate(d.methods) if c=='Lgh;' and n=='onSaveInstanceState' and i in d.code][0]
    off = d.code[m]; regs, ins, outs = struct.unpack_from('<HHH', raw, off)
    assert outs == 2, outs
    o = bytearray(raw); struct.pack_into('<H', o, off+4, 3); fix_hdr(o); return bytes(o)
if __name__ == '__main__':
    src, dst = sys.argv[1:3]; new = patch(zipfile.ZipFile(src).read('classes.dex'))
    rebuild_apk(src, dst, {'classes.dex': new})
    print('classes.dex sha256', hashlib.sha256(new).hexdigest()); print('wrote', dst)
