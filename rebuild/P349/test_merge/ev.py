import numpy as np
W,H,OW=8160,6144,8192
c=np.fromfile('clean.f32',np.float32).reshape(H,W)
o=np.fromfile('out.raw','<u2').reshape(H,OW)[:,:W].astype(np.float32)
f=np.fromfile('f0.raw','<u2').reshape(H,OW)[:,:W].astype(np.float32)
m=(slice(100,H-100),slice(100,W-100))
for nm,a in (('single',f),('merged',o)):
    e=(a-c)[m]; print(nm,'rmse',np.sqrt(np.mean(e**2)).round(2),'bias',e.mean().round(3))
# sharpness: green-channel high-pass correlation with clean
def hp(a):
    g=a[0::2,1::2]; return g[1:-1,1:-1]*4-g[:-2,1:-1]-g[2:,1:-1]-g[1:-1,:-2]-g[1:-1,2:]
hc,ho=hp(c),hp(o)
print('detail kept (hp regression slope merged vs clean):', (np.sum(hc*ho)/np.sum(hc*hc)).round(3))
print('moving object area mean (should be ~ clean, not 0.9 bright):', o[2100:2500,3100:3500].mean().round(1), c[2100:2500,3100:3500].mean().round(1))
