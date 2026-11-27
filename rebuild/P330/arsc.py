import struct,sys
def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def parse_pool(b,o):
    typ,hs,size=struct.unpack_from('<HHI',b,o)
    n,ns,flags,so,sto=struct.unpack_from('<IIIII',b,o+8)
    utf8=bool(flags&0x100)
    offs=[u32(b,o+hs+4*i) for i in range(n)]
    out=[]
    for off in offs:
        p=o+so+off
        if utf8:
            l=b[p]; p+=1
            if l&0x80: p+=1
            l=b[p]; p+=1
            if l&0x80: l=((l&0x7f)<<8)|b[p]; p+=1
            out.append(b[p:p+l].decode('utf8','replace'))
        else:
            l=u16(b,p); p+=2
            if l&0x8000: l=((l&0x7fff)<<16)|u16(b,p); p+=2
            out.append(b[p:p+2*l].decode('utf16','replace'))
    return out,dict(n=n,ns=ns,utf8=utf8,so=so,sto=sto,size=size,hs=hs)
def load(path):
    b=open(path,'rb').read()
    typ,hs,size,npk=struct.unpack_from('<HHII',b,0)
    o=hs
    gs,ginfo=parse_pool(b,o); gpo=o
    o+=u32(b,o+4)
    res={}  # id -> list of (config, type, key, value)
    while o<len(b):
        typ,hs,size=struct.unpack_from('<HHI',b,o)
        if typ==0x200:
            pid=u32(b,o+8)
            tso=u32(b,o+8+4+256); kso=u32(b,o+8+4+256+8)
            types,_=parse_pool(b,o+tso); keys,_=parse_pool(b,o+kso)
            p=o+hs
            while p<o+size:
                t,h,s=struct.unpack_from('<HHI',b,p)
                if t==0x201:
                    tid=b[p+8]; ec=u32(b,p+12); es=u32(b,p+16)
                    flags=b[p+9]
                    cfg=b[p+20:p+20+u32(b,p+20)]
                    for i in range(ec):
                        if flags&1:  # sparse
                            idx=u16(b,p+h+4*i); eo=u16(b,p+h+4*i+2)*4
                        else:
                            idx=i; eo=u32(b,p+h+4*i)
                            if eo==0xffffffff: continue
                        e=p+es+eo
                        esz,ef,kidx=struct.unpack_from('<HHI',b,e)
                        rid=(pid<<24)|(tid<<16)|idx
                        if ef&1: val=('bag',)
                        else:
                            vs,_,dt,d=struct.unpack_from('<HBBI',b,e+8)
                            val=(dt,d,e+8+4)
                        res.setdefault(rid,[]).append((cfg,types[tid-1],keys[kidx],val))
                p+=s
        o+=size
    return b,gs,ginfo,gpo,res
