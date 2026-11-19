import re
from dex import Dex, FMT, LEN
from dexpatch import Code, walk, branches
SAFE_CLS = ('Ljava/lang/String;','Ljava/lang/StringBuilder;','Landroid/util/Log;','Ljava/io/File;','Ljava/io/FileWriter;',
 'Ljava/io/PrintWriter;','Ljava/io/Writer;','Landroid/os/Environment;','Landroid/content/ContentValues;','Landroid/provider/MediaStore$Files;',
 'Landroid/content/ContentResolver;','Landroid/os/ParcelFileDescriptor;','Ljava/io/FileOutputStream;','Ljava/io/OutputStream;',
 'Ljava/lang/Long;','Ljava/lang/Integer;','Ljava/lang/Float;','Ljava/lang/Object;','Ljava/lang/Throwable;','Ljava/io/OutputStreamWriter;')
SAFE_M = {('Lcom/google/android/apps/camera/legacy/app/app/CameraApp;','getAppContext'),('Landroid/content/Context;','getExternalFilesDir'),
 ('Landroid/content/Context;','getContentResolver'),('Ljava/lang/System;','getProperties'),('Ljava/util/Map;','get'),('Landroid/net/Uri;','toString')}
WRITE = {('Ljava/io/FileWriter;','<init>'),('Landroid/content/ContentResolver;','insert'),('Ljava/io/FileOutputStream;','<init>'),('Ljava/io/PrintWriter;','println')}
def scan(d, mi, code=None):
    c = code or Code(d.b, d.code[mi]); w = c.w
    ins = {pc: ln for pc, ln, pay in walk(w) if not pay}
    br,_ = branches(w); out=[]
    for ti,(s,n,h) in enumerate(c.tries):
        e=s+n; pcs=[pc for pc in ins if s<=pc<e]
        writes=False; safe=True; why=''
        for pc in pcs:
            o=w[pc]&0xff
            if 0x6e<=o<=0x78:
                cls,_,nm=d.methods[w[pc+1]]
                if (cls,nm) in WRITE: writes=True
                if not (cls in SAFE_CLS or (cls,nm) in SAFE_M): safe=False; why=cls+'.'+nm
            elif o in (0x69,0x67,0x5b,0x59,0x4b,0x4d) or 0x67<=o<=0x6d or 0x59<=o<=0x5f: safe=False; why='store'
            elif o in (0x2b,0x2c,0x27,0x0e,0x0f,0x10,0x11): safe=False; why='switch/ret/throw'
        # exits: branches leaving the range must all go to one target X; fallthrough at e must be goto X
        tg=set(t for pc,f,t in br if s<=pc<e and not (s<=t<e))
        if e in ins and (w[e]&0xff) in (0x28,0x29,0x2a):
            tg.add([t for pc,f,t in br if pc==e][0])
        else: tg.add(e)
        handlers=c.handlers[h]
        hs=[a for _,a in handlers[0]]+([handlers[1]] if handlers[1] is not None else [])
        hx=set()
        for a in hs:
            p=a+1  # move-exception
            # follow simple linear handler until goto
            while p in ins and (w[p]&0xff) not in (0x28,0x29,0x2a): 
                o=w[p]&0xff
                if 0x6e<=o<=0x78:
                    cls,_,nm=d.methods[w[p+1]]
                    if not(cls in SAFE_CLS or (cls,nm) in SAFE_M): hx.add('unsafe'); break
                if o in (0x0e,0x0f,0x10,0x11,0x27): hx.add('ret'); break
                p+=ins[p]
            else:
                if p in ins: hx.add([t for pc,f,t in br if pc==p][0])
        if writes: out.append((ti,s,e,safe,why,sorted(tg,key=str),sorted(hx,key=str)))
    return out
