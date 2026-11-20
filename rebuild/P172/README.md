# P172 — checkpoint: P165 + P167 + P168, without P166

Base: P165 (classes.dex `a99b8203…3240`). Output classes.dex `6f2fb5dab93b1f99279f4794ca690ca26aeb6c9320571a03953ffd388906cc58`.
`build_p172.py` applies `build_p167.py` (burst-length cap) and `build_p168.py` (FocalLength = 35 mm-equivalent) on P165.

## Why P166 was dropped
With P166 (50 MP burst follows LMC "HDR++ exposure") the 50 MP output came out clearly brighter / flatter than 12 MP
(e.g. median 85–95 vs 67–71 on the same scene). P169 (burst exposure x0.707 / x0.6), P170 (frame metadata exposure x1.7)
and P171 (HDR+ shot exposure compensation -0.7 EV in 50 MP mode) did not fix it. With the link removed (P172) the 50 MP
burst copies the viewfinder ISO/exposure again (Auto rule: ISO > 2400 -> 2400, max 125 ms) and 12 MP / 50 MP pairs match
(user test 2026-11-20, several scenes). Only a very dark scene still differed: there the 50 MP session's viewfinder AE
chose ~0.8 EV more exposure (ISO ~5000 @ 1/20 s vs ISO ~4850 @ 1/33 s in the 12 MP session).

## P172L log (build_p172l.py, Download/merge.txt)
`frame <ljm> <timestamp> <SENSOR_DYNAMIC_BLACK_LEVEL[4]> <ISO> <exposure ns> <POST_RAW_SENSITIVITY_BOOST>` for every frame
handed to HDR+, plus the merge summary. Result: black level 64.2–64.4 on every frame (12 MP ZSL and 50 MP burst), boost 100.
