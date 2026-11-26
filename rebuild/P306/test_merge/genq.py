import numpy as np
W,H,OW,OH=8160,6128,8192,6144
src=np.memmap('/home/claude/rm1/SCA_20261124_081233.dng',dtype='<u2',mode='r',offset=6628,shape=(6144,8160,3))
rgb=src[:H].astype(np.float32)/65535.0*8.094
scale=0.18/np.mean(rgb)
rng=np.random.default_rng(2)
N=8; S,O=0.0032,2.4e-5
shifts=[(0,0)]+[(int(rng.integers(-40,41)),int(rng.integers(-40,41))) for _ in range(N-1)]
ys,xs=np.mgrid[0:H,0:W]
by=(ys//2)%2; bx=(xs//2)%2                     # quad: 2x2 blocks, RGGB block order
cfa=np.where((by==0)&(bx==0),0,np.where((by==1)&(bx==1),2,1)).astype(np.int8)
for k,(sx,sy) in enumerate(shifts):
    yy=np.clip(ys+sy,0,H-1); xx=np.clip(xs+sx,0,W-1)
    x=np.clip(rgb[yy,xx,cfa]*scale,0,1)
    if k==0: np.save('cleanq.npy',(64+959*x).astype(np.float32))
    xn=x+rng.standard_normal(x.shape).astype(np.float32)*np.sqrt(S*x+O)
    buf=np.zeros((OH,OW),'<u2'); buf[:H,:W]=np.clip(np.rint(64+959*xn),0,1023)
    buf.tofile(f'q{k}.raw'); print(k,sx,sy,flush=True)
