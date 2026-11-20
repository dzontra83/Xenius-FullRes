# P165L — 50 MP pipeline log (diagnostic, no ADB needed)

Base: P164B. Output classes.dex `14e4f1e5d4306da899d3fd21ffdec7f2f492da4c747ac635c547a0cc083227b7`.
Appends `<epoch ms> <event> <detail>` lines to `Download/merge.txt`; every write sits in its own catch-all try
(enclosing try ranges are split around it).

| event | where | detail |
|---|---|---|
| applied / rejected | Llfe.e, Llel.c | 8192x6144 RAW reader added to the session / exception text |
| capture | Llei.onCaptureCompleted (applied==7) | camera id of the burst |
| error | Llei burst build/submit handler | exception text |
| failed | Llei.onCaptureFailed (burst callback) | CaptureFailure reason (0 HAL error, 1 flushed) |
| image | Lleu.onImageAvailable | 50 MP frame size |
| frame | Ldvm.C | frame handed to HDR+ |
| merge | Lohy.accept | HDR+ merge summary |

Used to find the UW (ID4) bug fixed in P165. `python3 build_p165l.py XENIUS_P164B_20F_UNSIGNED.apk XENIUS_P165L_LOG_UNSIGNED.apk`
