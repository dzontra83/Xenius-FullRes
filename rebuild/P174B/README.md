# P174B — VerifyError fix (on P174)
P173's `Lgh.onSaveInstanceState` patch calls `substring(II)` (3 argument words) but outs_size stayed 2 → app start
VerifyError. outs_size → 3. classes.dex `00043e10…f1d8`.
