#!/usr/bin/env python3
"""Experimental XR green-guided chroma interpolation; no change to ER/SR or merge."""
from pathlib import Path
p=Path("rebuild/P290/quad.c")
s=p.read_text()
old="""            float dv = (1.f - fy) * ((1.f - fx) * da[xa] + fx * da[xb]) + fy * ((1.f - fx) * db[xa] + fx * db[xb]);
            d[x] = qround((float)G[x] + dv);"""
new="""            /* P292: green-guided interpolation of the RAW R-G / B-G grids.
               Prevent chroma of dark glass being blended into bright window frames. */
            int xx[2] = { xa, xb }, yy[2] = { ya, yb };
            float wx[2] = { 1.f - fx, fx }, wy[2] = { 1.f - fy, fy };
            float guide = (float)G[x], signal = guide > 64.f ? guide - 64.f : 0.f;
            float sigma = 12.f + 0.045f * signal;
            float sum = 0.f, accum = 0.f, near_d = 0.f, near_err = 1.e30f;
            for (int ky = 0; ky < 2; ++ky) {
                int gy = 4 * yy[ky] + o; if (gy + 1 >= h) gy = h - 2;
                for (int kx = 0; kx < 2; ++kx) {
                    int gx = 4 * xx[kx] + o; if (gx + 1 >= w) gx = w - 2;
                    const u16* gg = q_green + (i64)gy * w + gx;
                    float g = 0.25f * ((float)gg[0] + gg[1] + gg[w] + gg[w+1]);
                    float delta = guide - g;
                    float err = delta < 0.f ? -delta : delta;
                    float val = (float)D[(i64)yy[ky] * gw + xx[kx]];
                    if (err < near_err) { near_err = err; near_d = val; }
                    float t = delta / sigma;
                    float agree = 1.f / (1.f + t*t); agree *= agree;
                    float wgt = wx[kx] * wy[ky] * agree;
                    accum += wgt * val; sum += wgt;
                }
            }
            d[x] = qround(guide + (sum > 1.e-9f ? accum / sum : near_d));"""
assert s.count(old)==1, "P290 XR exact anchor not found"
assert s.count("static void q_xc(int y0, int y1) {")==1
a=s.replace(old,new)
p.write_text(a)
print("P292 native XR patch applied; original spatial/frequency merge unchanged.")
