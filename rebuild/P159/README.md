# Xenius P159 — 12 MP speed fix

**APK:** `XENIUS_P159_12MPFIX_UNSIGNED.apk` (unsigned). Built on P158B. classes.dex SHA-256
`5f24d4d4ca2a9e960d9777f359c2359992c0b1107bada94c2d97ae3399e099c5`; classes2.dex = P155.
**User-tested:** 12 MP back to normal speed, 50 MP as P158B.

## Bug (P157–P158B)
P157's per-frame waits in `Ldvm.p` (slot 2 and slots 3..N, up to 3 s each) also ran after every normal 12 MP payload
frame, where no 50 MP frame ever arrives, so 12 MP shots waited out the timeouts.

## Fix
Each wait runs only while a 50 MP burst is active: the slot-1 marker `new_RawWriteView__SWIG_1` is set (by the first
50 MP frame; kept by the feeder since P157; cleared at the next burst start; never set in 12 MP). No marker → no wait.
