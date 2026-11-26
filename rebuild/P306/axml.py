import struct,sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from arsc import parse_pool,u32,u16
def parse(b):
    o=8; strs=None; out=[]; resmap=[]
    while o<len(b):
        t,h,s=struct.unpack_from('<HHI',b,o)
        if t==1: strs,_=parse_pool(b,o)
        elif t==0x180: resmap=[u32(b,o+8+4*i) for i in range((s-8)//4)]
        elif t==0x102:
            ln=u32(b,o+8); ns,name=struct.unpack_from('<iI',b,o+16)
            ast,asz,ac=struct.unpack_from('<HHH',b,o+24)
            attrs=[]
            for i in range(ac):
                a=o+16+ast+i*asz
                ans,an,araw,vs,_,dt,d=struct.unpack_from('<iIiHBBI',b,a)
                attrs.append((strs[an],dt,d,strs[araw] if araw>=0 else None,a+12))
            out.append(('start',strs[name],attrs,o))
        elif t==0x103:
            out.append(('end',strs[struct.unpack_from('<I',b,o+20)[0]],None,o))
        o+=s
    return strs,out
