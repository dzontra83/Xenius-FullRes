# P173 — crash fixes (on P172)

From the LMC crash log (`/sdcard/LMC8.3/CRASH LOG/*.Prop`, 2026-11-20):
1. **Llei capture loop** — `CameraAccessException` when the camera errors while the 50 MP burst is queued → catch-all, the shot is dropped.
2. **Lldt.a** — NPE on an image with no matching request → the image is closed and skipped.
3. **Lgh.onSaveInstanceState** — `TransactionTooLargeException` from `android:fragments` → removed from the saved Bundle.

classes.dex `c3613921…9512`. P173 alone fails verification (outs_size of `Lgh.onSaveInstanceState` 2 < 3): use P174B.
