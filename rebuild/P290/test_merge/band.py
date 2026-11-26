import numpy as np,sys
W,H,OW=8160,6144,8192
c=np.fromfile('clean.f32',np.float32).reshape(H,W)
def load(fn): return np.fromfile(fn,'<u2').reshape(H,OW)[:,:W].astype(np.float32)
def g(a): return a[1000:5096:2,2000:6096:2+0][:, :2048] if False else a[1000:5096,2000:6096][0::2,1::2]
C=np.fft.rfft2(g(c)-g(c).mean())
fy=np.fft.fftfreq(2048)[:,None]; fx=np.fft.rfftfreq(2048)[None,:]; r=np.sqrt(fx**2+fy**2)
bands=[(0,.1),(.1,.2),(.2,.3),(.3,.4),(.4,.5)]
print('band(cyc/green-sample)  ', ' '.join(f'{a:.1f}-{b:.1f}' for a,b in bands))
for fn in sys.argv[1:]:
    A=np.fft.rfft2(g(load(fn))-g(load(fn)).mean())
    resp=[];noise=[]
    for a,b in bands:
        m=(r>=a)&(r<b)
        cc=np.sum(np.abs(C[m])**2); xc=np.sum((A[m]*np.conj(C[m])).real)
        resp.append(xc/cc); noise.append(np.sqrt(np.mean(np.abs(A[m]-C[m]*xc/cc)**2))/2048)
    print(f'{fn:10s} response',' '.join(f'{v:6.2f}' for v in resp),'| noise',' '.join(f'{v:6.2f}' for v in noise))
