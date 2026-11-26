import numpy as np, sys
W,H,OW,OH=8160,6144,8192,6144
src=np.memmap('/home/claude/rm1/SCA_20261124_081233.dng',dtype='<u2',mode='r',offset=6628,shape=(H,W,3))
rgb=src.astype(np.float32)/65535.0*8.094   # linear, ceiling
scale=0.18/np.mean(rgb)
rng=np.random.default_rng(1)
N=8; S,O=0.0032,2.4e-5
shifts=[(0,0)]+[(int(rng.integers(-40,41)),int(rng.integers(-40,41))) for _ in range(N-1)]
cfa=np.zeros((H,W),np.int8); cfa[0::2,1::2]=1; cfa[1::2,0::2]=1; cfa[1::2,1::2]=2
ys,xs=np.mgrid[0:H,0:W]
clean=None
for k,(sx,sy) in enumerate(shifts):
    # frame k sees the scene displaced: frame_k(p) = scene(p + s)  (merge then finds shift s)
    yy=np.clip(ys+sy,0,H-1); xx=np.clip(xs+sx,0,W-1)
    x=np.clip(rgb[yy,xx,cfa]*scale,0,1)
    if k==0: clean=(64+959*x).astype(np.float32)
    if k==3: x[2000:2600,3000:3600]=0.9   # moving object only in frame 3
    xn=x+rng.standard_normal(x.shape).astype(np.float32)*np.sqrt(S*x+O)
    code=np.clip(np.rint(64+959*xn),0,1023).astype('<u2')
    buf=np.zeros((OH,OW),'<u2'); buf[:,:W]=code
    buf.tofile(f'f{k}.raw'); print(k,sx,sy,flush=True)
clean.tofile('clean.f32')
