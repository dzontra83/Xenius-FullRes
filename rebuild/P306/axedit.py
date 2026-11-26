import struct,sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from arsc import parse_pool
from axml import parse
def enc_pool(strs,utf8):
    data=bytearray(); offs=[]
    for s in strs:
        offs.append(len(data))
        if utf8:
            e=s.encode('utf8'); n=len(s)
            data+= (bytes([n]) if n<0x80 else bytes([0x80|n>>8,n&0xff]))
            data+= (bytes([len(e)]) if len(e)<0x80 else bytes([0x80|len(e)>>8,len(e)&0xff]))
            data+=e+b'\0'
        else:
            e=s.encode('utf-16-le'); n=len(s)
            data+= struct.pack('<H',n) if n<0x8000 else struct.pack('<HH',0x8000|n>>16,n&0xffff)
            data+=e+b'\0\0'
    while len(data)%4: data+=b'\0'
    hs=28; so=hs+4*len(strs)
    hdr=struct.pack('<HHIIIIII',1,hs,so+len(data),len(strs),0,0x100 if utf8 else 0,so,0)
    return hdr+b''.join(struct.pack('<I',o) for o in offs)+bytes(data)
def add_strings(b,new):
    """append strings to the pool of a binary XML; returns (bytes, {string:index})"""
    o=8; t,h,s=struct.unpack_from('<HHI',b,o); assert t==1
    strs,info=parse_pool(b,o); assert info['ns']==0
    idx={}
    for x in new:
        if x in strs: idx[x]=strs.index(x)
        else: idx[x]=len(strs); strs.append(x)
    pool=enc_pool(strs,info['utf8'])
    out=bytearray(b[:8])+pool+b[o+s:]
    struct.pack_into('<I',out,4,len(out))
    return bytes(out),idx
def set_attr(b,elem_i,attr,dt,data,raw=-1):
    strs,ev=parse(b)
    k,n,a,o=[e for e in ev if e[0]=='start'][elem_i]
    for an,_,_,_,pos in a:
        if an==attr:
            ap=pos-12
            b=bytearray(b); struct.pack_into('<i',b,ap+8,raw)
            struct.pack_into('<HBBI',b,ap+12,8,0,dt,data); return bytes(b)
    raise KeyError(attr)
