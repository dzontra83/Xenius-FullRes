import sys,io
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from axml import parse
from axedit import add_strings,set_attr
from PIL import Image,ImageDraw
MOTION='M12.3,12.45a3.1,3.1 0 1,0 6.2,0a3.1,3.1 0 1,0 -6.2,0z M6.2,9.0h4.6v1.3h-4.6z M4.9,11.8h5.9v1.3h-5.9z M6.2,14.6h4.6v1.3h-4.6z'
def grid():
    s=2.4; g=0.8; x0=12.55-4.4; y0=12.45-4.4; p=[]
    for r in range(3):
        for c in range(3):
            p.append('M%.2f,%.2fh%.1fv%.1fh-%.1fz'%(x0+c*(s+g),y0+r*(s+g),s,s,s))
    return ' '.join(p)
GRID=grid()
SPLIT='M8.9,7.9H13.1A2.45,2.45 0 0,1 14,12.63L16.2,17H14.35L12.35,12.8H10.5V17H8.9Z M10.5,9.4V11.3H13.1A0.95,0.95 0 0,0 13.1,9.4Z'
def vec(tmpl,glyph):
    b,idx=add_strings(tmpl,[glyph,'M0,0'])
    for e,pd in ((3,glyph),(4,'M0,0'),(5,'M0,0')):
        b=set_attr(b,e,'pathData',3,idx[pd],idx[pd])
    return b
def png_r():
    import subprocess
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72"><rect x="6.25" y="6.25" width="59.5" height="59.5" rx="15" fill="none" stroke="#556666" stroke-width="6.5"/><g transform="translate(36,36) scale(2.7) translate(-12.55,-12.45)"><path fill="#556666" d="%s"/></g></svg>'%SPLIT
    return subprocess.run(['rsvg-convert'],input=svg.encode(),capture_output=True,check=True).stdout
def png(kind):
    if kind=='split': return png_r()
    S=288; im=Image.new('RGBA',(S,S),(0,0,0,0)); d=ImageDraw.Draw(im); col=(85,102,102,255)
    d.rounded_rectangle((12,12,S-12,S-12),radius=64,outline=col,width=26)
    if kind=='motion':
        d.ellipse((150,104,230,184),fill=col)
        for y,x0 in ((100,66),(136,48),(172,66)): d.rounded_rectangle((x0,y,134,y+18),radius=9,fill=col)
    elif kind=='split':
        d.rectangle((72,72,144,216),fill=col); d.rectangle((144,72,216,216),outline=col,width=16)
    else:
        s=40; g=12; x0=(S-(3*s+2*g))//2
        for r in range(3):
            for c in range(3):
                x=x0+c*(s+g); y=x0+r*(s+g); d.rectangle((x,y,x+s,y+s),fill=col)
    im=im.resize((72,72),Image.LANCZOS); o=io.BytesIO(); im.save(o,'PNG',optimize=True); return o.getvalue()
def prefs(b,lab):
    b,idx=add_strings(b,['Motion',lab])
    strs,ev=parse(b); st=[e for e in ev if e[0]=='start']
    for i,(k,n,a,o) in enumerate(st):
        key=[r for an,dt,d,r,_ in a if an=='key']
        if key==['pref_show_button_ldr']: b=set_attr(b,i,'title',3,idx['Motion'],idx['Motion'])
        if key==['pref_show_button_leica']: b=set_attr(b,i,'title',3,idx[lab],idx[lab])
    return b
def add_switch(b,after_key,key,title,summary):
    """P296: clone the switch preference whose key is after_key, insert the copy right after it with new key / title /
    summary strings (no other attribute changes)"""
    import struct
    b,idx=add_strings(b,[key,title,summary])
    strs,ev=parse(b)
    i=[j for j,e in enumerate(ev) if e[0]=='start' and any(r==after_key for an,dt,d,r,_ in e[2])][0]
    so=ev[i][3]; eo=ev[i+1][3]; assert ev[i+1][0]=='end'
    ssz=struct.unpack_from('<I',b,so+4)[0]; esz=struct.unpack_from('<I',b,eo+4)[0]
    st=bytearray(b[so:so+ssz]); en=bytes(b[eo:eo+esz])
    ast,asz,ac=struct.unpack_from('<HHH',st,24)
    for k in range(ac):
        a=16+ast+k*asz; an=struct.unpack_from('<I',st,a+4)[0]; nm=strs[an]
        v={'key':key,'title':title,'summary':summary}.get(nm)
        if v is not None:
            struct.pack_into('<i',st,a+8,idx[v]); struct.pack_into('<HBBI',st,a+12,8,0,3,idx[v])
    out=bytearray(b[:eo+esz])+st+en+b[eo+esz:]
    struct.pack_into('<I',out,4,len(out))
    return bytes(out)
def resources(z,compare=False,rem3=False):
    r={}
    off=z.read('res/drawable/ldr_off.xml'); on=z.read('res/drawable/ldr_on.xml')
    r['res/drawable/ldr_off.xml']=vec(off,MOTION); r['res/drawable/ldr_on.xml']=vec(on,MOTION)
    if rem3:
        from textpath import text_path
        r['res/drawable/leica_off.xml']=vec(on,text_path('ER')); r['res/drawable/leica_on.xml']=vec(on,text_path('SR'))
        r['res/drawable/aperture_on.xml']=vec(on,text_path('SR'))
        r['res/drawable/upscale_off.xml']=vec(on,text_path('12')); r['res/drawable/upscale_on.xml']=vec(on,text_path('50'))   # P274
        r['res/drawable/aperture_off.xml']=vec(on,text_path('25'))
        r['res/drawable-xxhdpi/hsl_ldr.png']=png('motion'); r['res/drawable-xxhdpi/hsl_leica.png']=png('split')
        r['res/xml/camera_preferences.xml']=add_switch(prefs(z.read('res/xml/camera_preferences.xml'),'Remosaic'),
            'pref_dirty_lens_detector_key','STATISTICS_FACE_DETECT_MODE','Disable face detection',
            'Faces no longer move focus and exposure')
        return r
    G=SPLIT if compare else GRID
    r['res/drawable/leica_off.xml']=vec(off,G); r['res/drawable/leica_on.xml']=vec(on,G)
    r['res/drawable-xxhdpi/hsl_ldr.png']=png('motion'); r['res/drawable-xxhdpi/hsl_leica.png']=png('split' if compare else 'grid')
    r['res/xml/camera_preferences.xml']=prefs(z.read('res/xml/camera_preferences.xml'),'Stock remosaic' if compare else '200MP')
    return r
if __name__=='__main__':
    import zipfile
    z=zipfile.ZipFile(sys.argv[1]); r=resources(z)
    for k,v in r.items():
        open('/tmp/icons_'+k.split('/')[-1],'wb').write(v)
        if k.endswith('.xml'):
            s,ev=parse(v); st=[e for e in ev if e[0]=='start']
            print(k,len(v),[(n,[(an,(r or '')[:30]) for an,dt,d,r,_ in a if an in('pathData','title','key')]) for _,n,a,_ in st][:6] if 'drawable' in k else '')
    s,ev=parse(r['res/xml/camera_preferences.xml'])
    for _,n,a,_ in [e for e in ev if e[0]=='start']:
        if any(r in('pref_show_button_ldr','pref_show_button_leica') for an,dt,d,r,_ in a): print([(an,dt,r) for an,dt,d,r,_ in a])
