import numpy as np, sys
W,H,OW=8160,6128,8192
def load(fn): return np.fromfile(fn,'<u2').reshape(6144,OW)[:H,:W].astype(np.float32)
c=load('truth.raw')
def g(a): return a[1000:5096,2000:6096][0::2,1::2]
C=np.fft.rfft2(g(c)-g(c).mean())
fy=np.fft.fftfreq(2048)[:,None]; fx=np.fft.rfftfreq(2048)[None,:]; r=np.sqrt(fx**2+fy**2)
bands=[(0,.1),(.1,.2),(.2,.3),(.3,.4),(.4,.5)]
for fn in sys.argv[1:]:
    a=load(fn); A=np.fft.rfft2(g(a)-g(a).mean()); resp=[];noise=[]
    for lo,hi in bands:
        m=(r>=lo)&(r<hi); cc=np.sum(np.abs(C[m])**2); xc=np.sum((A[m]*np.conj(C[m])).real)
        resp.append(xc/cc); noise.append(np.sqrt(np.mean(np.abs(A[m]-C[m]*xc/cc)**2))/2048)
    print(f'{fn:14s} resp',' '.join(f'{v:5.2f}' for v in resp),'| noise',' '.join(f'{v:6.2f}' for v in noise))
