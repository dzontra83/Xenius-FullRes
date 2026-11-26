import numpy as np, sys
OW=8192
s=np.fromfile(sys.argv[1],'<u2').reshape(6144,OW)[1900:2700,2900:3700].astype(np.float32)
for fn in sys.argv[2:]:
    m=np.fromfile(fn,'<u2').reshape(6144,OW)[1900:2700,2900:3700].astype(np.float32)
    d=np.abs(m-s); print(f'{fn:14s} ghost mean {d.mean():.2f}  p99 {np.percentile(d,99):.1f}  >30: {(d>30).mean()*100:.3f}%')
