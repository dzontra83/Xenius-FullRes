import numpy as np
from scipy import ndimage
W,H,OW,OH=8160,6128,8192,6144
src=np.memmap('/home/claude/rm1/SCA_20261124_081233.dng',dtype='<u2',mode='r',offset=6628,shape=(6144,8160,3))
rng=np.random.default_rng(3); N=8; S,O=0.0032,2.4e-5
shifts=[(0.0,0.0)]+[(float(rng.uniform(-40,40)),float(rng.uniform(-40,40))) for _ in range(N-1)]
ys,xs=np.mgrid[0:H,0:W]; by=(ys//2)%2; bx=(xs//2)%2
cfa=np.where((by==0)&(bx==0),0,np.where((by==1)&(bx==1),2,1)).astype(np.int8); del by,bx,ys,xs
scale=None
for k,(sx,sy) in enumerate(shifts):
    x=np.zeros((H,W),np.float32)
    for ch in range(3):
        p=src[:H,:,ch].astype(np.float32)/65535.0*8.094
        if scale is None: scale=0.18/float(np.mean(src[:H:4,::4,:].astype(np.float32)/65535.0*8.094))
        p*=scale
        if k: p=ndimage.shift(p,(-sy,-sx),order=5,mode='nearest')   # frame(p) = scene(p + s)
        x[cfa==ch]=p[cfa==ch]
    x=np.clip(x,0,1)
    if k==0:
        b=np.zeros((OH,OW),'<u2'); b[:H,:W]=np.clip(np.rint(64+959*x),0,1023); b.tofile('qsc.raw')
    xn=x+rng.standard_normal(x.shape).astype(np.float32)*np.sqrt(S*x+O)
    b=np.zeros((OH,OW),'<u2'); b[:H,:W]=np.clip(np.rint(64+959*xn),0,1023); b.tofile(f'qf{k}.raw'); print(k,round(sx,2),round(sy,2),flush=True)
