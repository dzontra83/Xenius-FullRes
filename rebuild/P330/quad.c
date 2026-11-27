/* Quad (2x2 same-colour blocks) -> Bayer remosaic, RGGB block order, for the vivo X300 Ultra main camera's native
   50 MP sensor mode (forceSensorMode 3). C port of RawR app/src/main/cpp/imaging/CfaRemosaic.h, quality Detail
   (GPL-3.0): pass A cubic directional green + per-pixel colour difference (raw - green) at R/B blocks; pass C
   per-pixel R/B from the wanted colour's pixels within 3 px (Gaussian distance, quartic green similarity, line fit
   regularised toward the colour-difference model). Own-colour sites keep the raw sample.
   Two passes over bands of rows on every thread with an atomic barrier between them. Scratch (green, diff) is
   mmap'ed once and kept. Input: src (stride rs bytes), w x h valid; output: dst with stride OW, valid area
   remosaiced, padding (to OW x OH) copied from the source. */

#define QB 16                                 /* rows per band (pass A: 8 groups) */
static u16* q_green; static short* q_diff; static i64 q_cap;
static struct { const u16* src; int rsw, w, h; u16* dst; float black; volatile int nextA, doneA, nextC, nbands; int mode; volatile int nextM, doneM, doneC, nextD1, doneD1, nextD2, doneD2, nextD3, doneD3, nextD4; float dnc, dnl;
                int qsc; const u16* osrc; int orsw; volatile int nextQ, doneQ; } qj;
#include "qsc_uw.h"
static float q_qtab[4][QSC_GY][QSC_GX];          /* blended inverse gains of this shot */
static u16* q_corr; static i64 q_corr_cap;

#ifdef HOST_TEST
extern void* malloc(unsigned long);
static void* q_mmap(i64 n) { return malloc((unsigned long)n); }
#else
static void* q_mmap(i64 n) {
    register long x0 __asm__("x0") = 0; register long x1 __asm__("x1") = n; register long x2 __asm__("x2") = 3;
    register long x3 __asm__("x3") = 0x22; register long x4 __asm__("x4") = -1; register long x5 __asm__("x5") = 0;
    register long x8 __asm__("x8") = 222;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory");
    return (x0 < 0 && x0 > -4096) ? 0 : (void*)x0;
}
#endif
static inline float qabs(float v) { return v < 0 ? -v : v; }
static inline float qmin(float a, float b) { return a < b ? a : b; }
static inline float qmax(float a, float b) { return a > b ? a : b; }
static inline int qch(int bx, int by) { int i = ((by & 1) << 1) | (bx & 1); return i == 0 ? 0 : (i == 3 ? 2 : 1); }  /* RGGB */
static inline float qherm(float p0, float p1, float m0, float m1, float t) {
    float t2 = t * t, t3 = t2 * t;
    float v = (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1;
    float lo = qmin(p0, p1), hi = qmax(p0, p1); return v < lo ? lo : (v > hi ? hi : v);
}
static inline int qrs(float v) { return v < 0 ? -(int)(0.5f - v) : (int)(v + 0.5f); }
static inline u16 qround(float v) { if (v < 0) v = 0; if (v > 65535) v = 65535; return (u16)(int)(v + 0.5f); }
/* output pool: native buffers handed to Java as direct ByteBuffers (outside the Java heap); a slot is busy from
   acquire until the frame's Llet is closed */
#define QPOOL 40
static void* q_pool[QPOOL]; static int q_busy[QPOOL];
static void* q_acquire(void) {
    for (int i = 0; i < QPOOL; ++i) {
        int z = 0;
        if (__atomic_compare_exchange_n(&q_busy[i], &z, 1, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) {
            if (!q_pool[i]) q_pool[i] = q_mmap((i64)OW * OH * 2);
            if (!q_pool[i]) { __atomic_store_n(&q_busy[i], 0, __ATOMIC_SEQ_CST); return 0; }
            return q_pool[i];
        }
    }
    return 0;
}
static int q_release(const void* p) {
    for (int i = 0; i < QPOOL; ++i) if (q_pool[i] && q_pool[i] == p) { __atomic_store_n(&q_busy[i], 0, __ATOMIC_SEQ_CST); return 1; }
    return 0;
}
static int q_inuse(void) { int n = 0; for (int i = 0; i < QPOOL; ++i) n += q_busy[i]; return n; }
/* one conversion at a time (the remosaic state is global): taken in quad_start, dropped in tbin_finish */
static int q_lock;
static volatile int q_doneD4;
static void q_yield(void) {
#ifndef HOST_TEST
    register long x8 __asm__("x8") = 124; register long x0 __asm__("x0") = 0;   /* sched_yield */
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x8) : "memory");
#endif
}
static int q_take(void) {
    for (long n = 0; n < 20000000L; ++n) {
        int z = 0;
        if (__atomic_compare_exchange_n(&q_lock, &z, 1, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) return 1;
        q_yield();
    }
    return 0;
}
static void q_drop(void) { __atomic_store_n(&q_lock, 0, __ATOMIC_SEQ_CST); }
#define RAW(xx, yy) ((float)qj.src[(i64)(yy) * qj.rsw + (xx)])

/* edge pixels: RawR CfaRemosaicGreen::at, n = 2, cubic */
static float q_green_at(int X, int Y) {
    int w = qj.w, h = qj.h;
#define PX(xx, yy) RAW(clampi((xx), 0, w - 1), clampi((yy), 0, h - 1))
    if (qch(X >> 1, Y >> 1) == 1) return PX(X, Y);
    int x0 = X & ~1, y0 = Y & ~1;
    int xl = x0 - 1 >= 0 ? x0 - 1 : x0 + 2, xr = x0 + 2 < w ? x0 + 2 : xl;
    int yt = y0 - 1 >= 0 ? y0 - 1 : y0 + 2, yb = y0 + 2 < h ? y0 + 2 : yt;
    float gl = PX(xl, Y), gr = PX(xr, Y), gt = PX(X, yt), gb = PX(X, yb);
    float th = xr != xl ? (float)(X - xl) / (float)(xr - xl) : 0.5f, tv = yb != yt ? (float)(Y - yt) / (float)(yb - yt) : 0.5f;
    float gh = gl + (gr - gl) * th, gv = gt + (gb - gt) * tv;
    if (xr != xl) { float len = (float)(xr - xl); gh = qherm(gl, gr, (gl - PX(xl - 1 < 0 ? 0 : xl - 1, Y)) * len, (PX(xr + 1 > w - 1 ? w - 1 : xr + 1, Y) - gr) * len, th); }
    if (yb != yt) { float len = (float)(yb - yt); gv = qherm(gt, gb, (gt - PX(X, yt - 1 < 0 ? 0 : yt - 1)) * len, (PX(X, yb + 1 > h - 1 ? h - 1 : yb + 1) - gb) * len, tv); }
    float ah = qabs(gl - gr) + qabs(PX(x0, Y) - PX(x0 + 1, Y)) + 0.5f * qabs(PX(x0 - 3, Y) - PX(x0 + 4, Y));
    float av = qabs(gt - gb) + qabs(PX(X, y0) - PX(X, y0 + 1)) + 0.5f * qabs(PX(X, y0 - 3) - PX(X, y0 + 4));
    float wh = 1.f / ((ah + 1) * (ah + 1)), wv = 1.f / ((av + 1) * (av + 1));
    return (wh * gh + wv * gv) / (wh + wv);
#undef PX
}

typedef float qv4 __attribute__((vector_size(16)));
typedef int qi4 __attribute__((vector_size(16)));
static inline qv4 qv_sel(qi4 m, qv4 a, qv4 b) { return (qv4)(((qi4)a & m) | ((qi4)b & ~m)); }
static void q_a_group(int gx, int gy) {
    int w = qj.w, h = qj.h;
    {
            int x0 = gx * 2, y0 = gy * 2;
            int colour = qch(gx, gy) != 1;
            if (!colour) {
                for (int j = 0; j < 2 && y0 + j < h; ++j)
                    for (int i = 0; i < 2 && x0 + i < w; ++i) { i64 k = (i64)(y0 + j) * w + x0 + i; q_green[k] = (u16)RAW(x0 + i, y0 + j); }
                return;
            }
            int interior = x0 >= 4 && y0 >= 4 && x0 + 5 < w && y0 + 5 < h;
            float g[2][2];
            if (!interior) {
                for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i)
                    g[j][i] = (y0 + j < h && x0 + i < w) ? q_green_at(x0 + i, y0 + j) : 0;
            } else {
                float gh[2][2], ah[2], gv[2][2], av[2];
                for (int j = 0; j < 2; ++j) {
                    const u16* r = qj.src + (i64)(y0 + j) * qj.rsw;
                    float gl = r[x0 - 1], gr = r[x0 + 2];
                    ah[j] = qabs(gl - gr) + qabs((float)r[x0] - (float)r[x0 + 1]) + 0.5f * qabs((float)r[x0 - 3] - (float)r[x0 + 4]);
                    for (int i = 0; i < 2; ++i)
                        gh[j][i] = qherm(gl, gr, (gl - (float)r[x0 - 2]) * 3.f, ((float)r[x0 + 3] - gr) * 3.f, (float)(i + 1) / 3.f);
                }
                for (int i = 0; i < 2; ++i) {
                    const u16* c = qj.src + x0 + i; i64 s = qj.rsw;
                    float gt = c[(y0 - 1) * s], gb = c[(y0 + 2) * s];
                    av[i] = qabs(gt - gb) + qabs((float)c[y0 * s] - (float)c[(y0 + 1) * s]) + 0.5f * qabs((float)c[(y0 - 3) * s] - (float)c[(y0 + 4) * s]);
                    for (int j = 0; j < 2; ++j)
                        gv[j][i] = qherm(gt, gb, (gt - (float)c[(y0 - 2) * s]) * 3.f, ((float)c[(y0 + 3) * s] - gb) * 3.f, (float)(j + 1) / 3.f);
                }
                for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i) {
                    float a = (ah[j] + 1) * (ah[j] + 1), b = (av[i] + 1) * (av[i] + 1);
                    g[j][i] = (gh[j][i] * b + gv[j][i] * a) / (a + b);
                }
            }
            for (int j = 0; j < 2 && y0 + j < h; ++j)
                for (int i = 0; i < 2 && x0 + i < w; ++i) {
                    i64 k = (i64)(y0 + j) * w + x0 + i;
                    q_green[k] = qround(g[j][i]);
                }
        }
}

/* P268: pass A, 4 colour groups at once (gx, gx+2, gx+4, gx+6 = x0 + 4 L), interior only; each lane runs the scalar
   interior arithmetic (same operations, same order) -> same output. QA_VEC 0 = scalar only. */
#ifndef QA_VEC
#define QA_VEC 1
#endif
static inline qv4 qv_abs(qv4 v) { return qv_sel(v < 0, -v, v); }
static inline qv4 qv_herm(qv4 p0, qv4 p1, qv4 m0, qv4 m1, float t) {
    float t2 = t * t, t3 = t2 * t;
    qv4 v = (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1;
    qv4 lo = qv_sel(p0 < p1, p0, p1), hi = qv_sel(p0 > p1, p0, p1);
    return qv_sel(v < lo, lo, qv_sel(v > hi, hi, v));
}
static void q_a_vec4(int x0, int y0) {
    int w = qj.w; i64 s = qj.rsw;
#define QL(p) ((qv4){(float)(p)[0], (float)(p)[4], (float)(p)[8], (float)(p)[12]})
    qv4 gh[2][2], ah[2], gv[2][2], av[2];
    for (int j = 0; j < 2; ++j) {
        const u16* r = qj.src + (i64)(y0 + j) * s + x0;
        qv4 gl = QL(r - 1), gr = QL(r + 2), r0 = QL(r), r1 = QL(r + 1), rm3 = QL(r - 3), rp4 = QL(r + 4), rm2 = QL(r - 2), rp3 = QL(r + 3);
        ah[j] = qv_abs(gl - gr) + qv_abs(r0 - r1) + 0.5f * qv_abs(rm3 - rp4);
        for (int i = 0; i < 2; ++i)
            gh[j][i] = qv_herm(gl, gr, (gl - rm2) * 3.f, (rp3 - gr) * 3.f, (float)(i + 1) / 3.f);
    }
    for (int i = 0; i < 2; ++i) {
        const u16* c = qj.src + x0 + i;
        qv4 gt = QL(c + (y0 - 1) * s), gb = QL(c + (y0 + 2) * s), c0 = QL(c + y0 * s), c1 = QL(c + (y0 + 1) * s);
        qv4 cm3 = QL(c + (y0 - 3) * s), cp4 = QL(c + (y0 + 4) * s), cm2 = QL(c + (y0 - 2) * s), cp3 = QL(c + (y0 + 3) * s);
        av[i] = qv_abs(gt - gb) + qv_abs(c0 - c1) + 0.5f * qv_abs(cm3 - cp4);
        for (int j = 0; j < 2; ++j)
            gv[j][i] = qv_herm(gt, gb, (gt - cm2) * 3.f, (cp3 - gb) * 3.f, (float)(j + 1) / 3.f);
    }
#undef QL
    for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i) {
        qv4 a = (ah[j] + 1) * (ah[j] + 1), b = (av[i] + 1) * (av[i] + 1);
        qv4 g = (gh[j][i] * b + gv[j][i] * a) / (a + b);
        u16* o = q_green + (i64)(y0 + j) * w + x0 + i;
        for (int L = 0; L < 4; ++L) o[4 * L] = qround(g[L]);
    }
}
static void q_passA(int gy0, int gy1) {                      /* groups of 2 rows */
    int w = qj.w, h = qj.h, gw = (w + 1) / 2;
    for (int gy = gy0; gy < gy1; ++gy) {
        int y0 = gy * 2, p = gy & 1;                          /* colour groups: gx parity == gy parity (RGGB) */
        int rowint = y0 >= 4 && y0 + 5 < h;
        for (int gx = 1 - p; gx < gw; gx += 2) q_a_group(gx, gy);   /* green groups: copy */
        for (int gx = p; gx < gw; ) {
            int x0 = gx * 2;
            if (QA_VEC && rowint && x0 >= 4 && x0 + 12 + 5 < w) { q_a_vec4(x0, y0); gx += 8; }
            else { q_a_group(gx, gy); gx += 2; }
        }
    }
}

/* RawR Detail (2026-11-22 update): R/B at a foreign site from a colour line T = a*G + b fitted to the wanted
   colour's 2x2 blocks within 7 px, each block as its moments (mean green, mean sample, green variance, green/sample
   covariance), Gaussian distance weight exp(-0.06 d^2), quartic similarity of its mean green to the pixel's green,
   slope regularised toward 1 (lambda 4); the line is evaluated at the pixel's own green. */
typedef struct { float g, v, gg, gv; } qmom;              /* 16 bytes; stored in the q_diff scratch (same size) */
typedef struct { signed char dbx, dby; float sp; } qtap;
static qtap q_taps[4][4][64]; static int q_ntaps[4][4]; static int q_tapsok;
static float q_exp(float x) {                                 /* e^x, x <= 0, small range */
    float r = 1, t = 1; for (int k = 1; k < 40; ++k) { t *= x / (float)k; r += t; } return r;
}
static void q_build_taps(void) {
    if (q_tapsok) return;
    for (int py = 0; py < 4; ++py)
        for (int px = 0; px < 4; ++px) {
            int want = qch(px, py), n = 0;                    /* Bayer site colour (RGGB at pixel level) */
            if (want == 1 || qch(px >> 1, py >> 1) == want) { q_ntaps[py][px] = 0; continue; }
            for (int dby = -4; dby <= 4; ++dby)
                for (int dbx = -4; dbx <= 4; ++dbx) {
                    int bx = (px >> 1) + dbx, by = (py >> 1) + dby;
                    if (qch(bx & 1, by & 1) != want) continue;
                    int tx = 4 * bx + 1 - 2 * px, ty = 4 * by + 1 - 2 * py;
                    if (tx * tx + ty * ty > 196 || n >= 64) continue;
                    q_taps[py][px][n].dbx = (signed char)dbx; q_taps[py][px][n].dby = (signed char)dby;
                    q_taps[py][px][n].sp = q_exp(-0.015f * (float)(tx * tx + ty * ty)); ++n;
                }
            q_ntaps[py][px] = n;
        }
    q_tapsok = 1;
}
static void q_passM(int by0, int by1) {                     /* block rows */
    int w = qj.w, h = qj.h, bw = (w + 1) / 2, mw = (bw + 1) / 2; qmom* M = (qmom*)q_diff;
    for (int by = by0; by < by1; ++by)
        for (int bx = 0; bx < bw; ++bx) {
            if (qch(bx, by) == 1) continue;
            float g[4], v[4]; int k = 0;
            for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i, ++k) {
                int yy = 2 * by + j, xx = 2 * bx + i; if (yy > h - 1) yy = h - 1; if (xx > w - 1) xx = w - 1;
                g[k] = (float)q_green[(i64)yy * w + xx]; v[k] = RAW(xx, yy);
            }
            qmom m; m.g = 0.25f * ((g[0] + g[1]) + (g[2] + g[3])); m.v = 0.25f * ((v[0] + v[1]) + (v[2] + v[3]));
            m.gg = 0; m.gv = 0;
            for (k = 0; k < 4; ++k) { float dg = g[k] - m.g; m.gg += dg * dg; m.gv += dg * (v[k] - m.v); }
            M[(i64)by * mw + (bx >> 1)] = m;
        }
}
/* P268: pass C, 4 pixels at once. Pixels x, x+4, x+8, x+12 of a row have the same tap set (same x & 3) and their
   block moments for a tap are 4 consecutive qmom entries (bx + 2 per lane -> M index + 1), so each lane runs exactly
   the scalar per-tap arithmetic (same operations, same order) on its own data: the output is the same as the scalar
   code. Border groups and green / own-colour sites use the scalar path. QC_VEC 0 = scalar only. */
#ifndef QC_VEC
#define QC_VEC 1
#endif
static inline float q_c_fin(float g0, float sw, float su, float sv, float suu, float suv, float umin, float umax) {
    float v = g0;
    if (sw > 0) {
        float mu = su / sw, mv = sv / sw;
        float var = suu / sw - mu * mu, cov = suv / sw - mu * mv;
        float slope = (cov + 4.f) / (var + 4.f);
        float margin = umax - umin;
        float uh = 0; if (uh < umin - margin) uh = umin - margin; if (uh > umax + margin) uh = umax + margin;
        v = g0 + mv + slope * (uh - mu) - uh;
    }
    return v;
}
static inline void q_c_px(int x, int y, u16* out, const qmom* M, int w, int bw, int bh, int mw) {
    int n = q_ntaps[y & 3][x & 3];
    i64 i = (i64)y * w + x;
    float g0 = (float)q_green[i];
    if (!n) {
        if (qch(x & 1, y & 1) != 1) { out[x] = (u16)RAW(x, y); return; }   /* own colour: raw sample */
        out[x] = q_green[i]; return;                                      /* green site */
    }
    const qtap* t = q_taps[y & 3][x & 3];
    int bx0 = x >> 1, by0 = y >> 1;
    int interior = bx0 >= 4 && by0 >= 4 && bx0 + 4 < bw && by0 + 4 < bh;
    float sw = 0, su = 0, sv = 0, suu = 0, suv = 0, umin = 1e30f, umax = -1e30f;
    for (int k = 0; k < n; ++k) {
        int bx = bx0 + t[k].dbx, by = by0 + t[k].dby;
        if (!interior && (bx < 0 || by < 0 || bx >= bw || by >= bh)) continue;
        const qmom* m = &M[(i64)by * mw + (bx >> 1)];
        float d = m->g - g0, e = m->v - g0;
        float sg = 0.5f * qmax(g0, m->g) + 4.f;
        float s2 = sg * sg, s4 = s2 * s2, d2 = d * d;
        float wgt = t[k].sp * s4 / (s4 + d2 * d2);
        sw += 4.f * wgt; su += 4.f * wgt * d; sv += 4.f * wgt * e;
        suu += wgt * (m->gg + 4.f * d * d); suv += wgt * (m->gv + 4.f * d * e);
        if (wgt > 1e-3f) { umin = qmin(umin, d); umax = qmax(umax, d); }
    }
    out[x] = qround(q_c_fin(g0, sw, su, sv, suu, suv, umin, umax));
}
static void q_passC(int y0, int y1) {
    int w = qj.w, h = qj.h, bw = (w + 1) / 2, bh = (h + 1) / 2, mw = (bw + 1) / 2; const qmom* M = (const qmom*)q_diff;
    for (int y = y0; y < y1; ++y) {
        u16* out = qj.dst + (i64)y * OW;
        int by0 = y >> 1, x = 0;
        if (QC_VEC && by0 >= 4 && by0 + 4 < bh)
            for (; x + 16 <= w; x += 16) for (int c = 0; c < 4; ++c) {
                int xc = x + c, n = q_ntaps[y & 3][xc & 3], bx0 = xc >> 1;
                if (!n || bx0 < 4 || bx0 + 6 + 4 >= bw) { for (int L = 0; L < 4; ++L) q_c_px(xc + 4 * L, y, out, M, w, bw, bh, mw); continue; }
                const u16* gr = q_green + (i64)y * w + xc;
                qv4 g0 = {(float)gr[0], (float)gr[4], (float)gr[8], (float)gr[12]};
                qv4 sw = {0, 0, 0, 0}, su = sw, sv = sw, suu = sw, suv = sw;
                qv4 umin = {1e30f, 1e30f, 1e30f, 1e30f}, umax = {-1e30f, -1e30f, -1e30f, -1e30f};
                const qtap* t = q_taps[y & 3][xc & 3];
                for (int k = 0; k < n; ++k) {
                    const qmom* m = &M[(i64)(by0 + t[k].dby) * mw + ((bx0 + t[k].dbx) >> 1)];
                    qv4 mg = {m[0].g, m[1].g, m[2].g, m[3].g}, mv = {m[0].v, m[1].v, m[2].v, m[3].v};
                    qv4 mgg = {m[0].gg, m[1].gg, m[2].gg, m[3].gg}, mgv = {m[0].gv, m[1].gv, m[2].gv, m[3].gv};
                    qv4 d = mg - g0, e = mv - g0;
                    qv4 sg = 0.5f * qv_sel(g0 > mg, g0, mg) + 4.f;
                    qv4 s2 = sg * sg, s4 = s2 * s2, d2 = d * d;
                    qv4 wgt = t[k].sp * s4 / (s4 + d2 * d2);
                    sw += 4.f * wgt; su += 4.f * wgt * d; sv += 4.f * wgt * e;
                    suu += wgt * (mgg + 4.f * d * d); suv += wgt * (mgv + 4.f * d * e);
                    qi4 on = wgt > 1e-3f;
                    umin = qv_sel(on, qv_sel(umin < d, umin, d), umin); umax = qv_sel(on, qv_sel(umax > d, umax, d), umax);
                }
                for (int L = 0; L < 4; ++L) out[xc + 4 * L] = qround(q_c_fin(g0[L], sw[L], su[L], sv[L], suu[L], suv[L], umin[L], umax[L]));
            }
        for (; x < w; ++x) q_c_px(x, y, out, M, w, bw, bh, mw);
    }
}

/* Light denoise after the remosaic (XR / ER), on the Bayer output, per 2x2 block (R, Gr, Gb, B; G = (Gr+Gb)/2):
   chroma: colour differences R-G and B-G smoothed over 5x5 blocks, edge-aware (weights from green and chroma
   similarity, rational falloff scaled to the signal), blended by dnc; luma: block green smoothed over 3x3 blocks,
   edge-aware, blended by dnl, the change added to all 4 pixels. Blocks with a near-clipped pixel are kept. */
#define QDN_CLIP 1000
#ifndef QDR
#define QDR 1
#endif
static inline float q_rcp(float x) {   /* 1/x, x >= 1: bit trick + one Newton step (~0.2 %) */
    union { float f; int i; } u; u.f = x; u.i = 0x7EF311C3 - u.i; float r = u.f; return r * (2.f - x * r);
}
static inline int q_abs(int v) { return v < 0 ? -v : v; }
/* scratch layout (q_diff, shorts): G, Cr, Cb at block res (bw x bh), then G2, Cr2, Cb2 at half block res
   and the filtered Cr2f, Cb2f (hw x hh) */
#define QDN_PL ((i64)q_cap / 4 + 4096)
#define QDN_P2 ((i64)q_cap / 16 + 4096)
static void q_dn1(int by0, int by1) {          /* block planes */
    int w = qj.w, bw = w / 2; u16* G = (u16*)q_diff; short* Cr = q_diff + QDN_PL; short* Cb = Cr + QDN_PL;
    for (int by = by0; by < by1; ++by) {
        const u16* r0 = qj.dst + (i64)(2 * by) * OW; const u16* r1 = r0 + OW; i64 o = (i64)by * bw;
        for (int bx = 0; bx < bw; ++bx) {
            int R = r0[2 * bx], g1 = r0[2 * bx + 1], g2 = r1[2 * bx], B = r1[2 * bx + 1];
            int g = (g1 + g2 + 1) >> 1;
            G[o + bx] = (u16)((R >= QDN_CLIP || g1 >= QDN_CLIP || g2 >= QDN_CLIP || B >= QDN_CLIP) ? 0xffff : g);
            Cr[o + bx] = (short)(R - g); Cb[o + bx] = (short)(B - g);
        }
    }
}
static void q_dn2(int hy0, int hy1) {          /* half block res: average 2x2 blocks */
    int w = qj.w, bw = w / 2, hw = bw / 2; const u16* G = (const u16*)q_diff; const short* Cr = q_diff + QDN_PL; const short* Cb = Cr + QDN_PL;
    short* base2 = q_diff + 3 * QDN_PL; u16* G2 = (u16*)base2; short* Cr2 = base2 + QDN_P2; short* Cb2 = Cr2 + QDN_P2;
    for (int hy = hy0; hy < hy1; ++hy)
        for (int hx = 0; hx < hw; ++hx) {
            i64 a = (i64)(2 * hy) * bw + 2 * hx, b = a + bw;
            int ga = G[a], gb = G[a + 1], gc = G[b], gd = G[b + 1];
            i64 o = (i64)hy * hw + hx;
            if (ga == 0xffff || gb == 0xffff || gc == 0xffff || gd == 0xffff) { G2[o] = 0xffff; Cr2[o] = Cb2[o] = 0; continue; }
            G2[o] = (u16)((ga + gb + gc + gd + 2) >> 2);
            Cr2[o] = (short)((Cr[a] + Cr[a + 1] + Cr[b] + Cr[b + 1]) / 4); Cb2[o] = (short)((Cb[a] + Cb[a + 1] + Cb[b] + Cb[b + 1]) / 4);
        }
}
static void q_dn3(int hy0, int hy1) {          /* half res 3x3 edge-aware chroma filter */
    int w = qj.w, h = qj.h, hw = w / 4, hh = h / 4; float blk = qj.black;
    short* base2 = q_diff + 3 * QDN_PL; const u16* G2 = (const u16*)base2; const short* Cr2 = base2 + QDN_P2; const short* Cb2 = Cr2 + QDN_P2;
    short* Crf = (short*)(Cb2 + QDN_P2); short* Cbf = Crf + QDN_P2;
    for (int hy = hy0; hy < hy1; ++hy) {
        int ya = hy > 0 ? hy - 1 : 0, yb = hy < hh - 1 ? hy + 1 : hy;
        const u16* gr[3] = { G2 + (i64)ya * hw, G2 + (i64)hy * hw, G2 + (i64)yb * hw };
        const short* rr[3] = { Cr2 + (i64)ya * hw, Cr2 + (i64)hy * hw, Cr2 + (i64)yb * hw };
        const short* br[3] = { Cb2 + (i64)ya * hw, Cb2 + (i64)hy * hw, Cb2 + (i64)yb * hw };
        for (int hx = 0; hx < hw; ++hx) {
            i64 o = (i64)hy * hw + hx; int g0 = gr[1][hx];
            if (g0 == 0xffff) { Crf[o] = rr[1][hx]; Cbf[o] = br[1][hx]; continue; }
            float gs = (float)g0 - blk; if (gs < 0) gs = 0;
            float isg = q_rcp(0.04f * gs + 3.f), icc = q_rcp(0.06f * gs + 4.f);
            int cr0 = rr[1][hx], cb0 = br[1][hx];
            int xs[3] = { hx > 0 ? hx - 1 : 0, hx, hx < hw - 1 ? hx + 1 : hx };
            float wc = 0, ar = 0, ab = 0;
            for (int k = 0; k < 3; ++k)
                for (int l = 0; l < 3; ++l) {
                    int xx = xs[l], g = gr[k][xx]; if (g == 0xffff) continue;
                    float u = (float)(g - g0) * isg, v = (float)(q_abs(rr[k][xx] - cr0) + q_abs(br[k][xx] - cb0)) * icc;
                    float t = 1.f + u * u + v * v;
                    float wt = ((k == 1) + (l == 1) == 2 ? 1.f : ((k == 1) || (l == 1) ? 0.6f : 0.36f)) * q_rcp(t * t);
                    wc += wt; ar += wt * (float)rr[k][xx]; ab += wt * (float)br[k][xx];
                }
            float iw = q_rcp(wc);
            Crf[o] = (short)qrs(ar * iw); Cbf[o] = (short)qrs(ab * iw);
        }
    }
}
static void q_dn4(int by0, int by1) {          /* back to block res: add the filtered half-res chroma change, light luma */
    int w = qj.w, h = qj.h, bw = w / 2, bh = h / 2, hw = bw / 2, hh = bh / 2;
    const u16* G = (const u16*)q_diff; const short* Cr = q_diff + QDN_PL; const short* Cb = Cr + QDN_PL;
    short* base2 = q_diff + 3 * QDN_PL; const short* Cr2 = base2 + QDN_P2; const short* Cb2 = Cr2 + QDN_P2;
    const short* Crf = Cb2 + QDN_P2; const short* Cbf = Crf + QDN_P2;
    float sc = qj.dnc, sl = qj.dnl, blk = qj.black;
    for (int by = by0; by < by1; ++by) {
        u16* r0 = qj.dst + (i64)(2 * by) * OW; u16* r1 = r0 + OW;
        int hy = by >> 1; if (hy > hh - 1) hy = hh - 1;
        int up = (by & 1) ? (hy + 1 < hh ? hy + 1 : hy) : (hy > 0 ? hy - 1 : 0);   /* bilinear: nearest + the neighbour row */
        for (int bx = 0; bx < bw; ++bx) {
            i64 o = (i64)by * bw + bx; int g0 = G[o]; if (g0 == 0xffff) continue;
            int hx = bx >> 1; if (hx > hw - 1) hx = hw - 1;
            int lx = (bx & 1) ? (hx + 1 < hw ? hx + 1 : hx) : (hx > 0 ? hx - 1 : 0);
            i64 a = (i64)hy * hw + hx, b = (i64)hy * hw + lx, c = (i64)up * hw + hx, d = (i64)up * hw + lx;
            float fr = 0.5625f * Crf[a] + 0.1875f * (Crf[b] + Crf[c]) + 0.0625f * Crf[d];      /* smoothed chroma here */
            float fb = 0.5625f * Cbf[a] + 0.1875f * (Cbf[b] + Cbf[c]) + 0.0625f * Cbf[d];
            const u16* G2 = (const u16*)base2;
            float gi = 0.5625f * G2[a] + 0.1875f * (G2[b] + G2[c]) + 0.0625f * G2[d];
            float gsb = (float)g0 - blk; if (gsb < 0) gsb = 0;
            float ccs = q_rcp(0.08f * gsb + 5.f), gg = q_rcp(0.05f * gsb + 3.f);
            float dr = fr - (float)Cr[o], db = fb - (float)Cb[o];
            float u = ((dr < 0 ? -dr : dr) + (db < 0 ? -db : db)) * ccs, v = ((float)g0 - gi) * gg;   /* guard: real colour / luma edges */
            float tg = 1.f + u * u + v * v, gw = q_rcp(tg * tg);
            if (G2[a] == 0xffff || G2[b] == 0xffff || G2[c] == 0xffff || G2[d] == 0xffff) gw = 0;
            dr *= gw; db *= gw;
            float crn = (float)Cr[o] + sc * dr, cbn = (float)Cb[o] + sc * db, gn = (float)g0;
            if (sl > 0) {                         /* luma: plus-shaped 5 taps on block green, edge-aware */
                float gs = (float)g0 - blk; if (gs < 0) gs = 0; float isg = q_rcp(0.05f * gs + 3.f);
                float wl = 1.f, ag = (float)g0;
                int nx[4] = { bx > 0 ? bx - 1 : bx, bx < bw - 1 ? bx + 1 : bx, bx, bx };
                int ny[4] = { by, by, by > 0 ? by - 1 : by, by < bh - 1 ? by + 1 : by };
                for (int k = 0; k < 4; ++k) {
                    int g = G[(i64)ny[k] * bw + nx[k]]; if (g == 0xffff) continue;
                    float u = (float)(g - g0) * isg, t = 1.f + u * u, wt = 0.6f * q_rcp(t * t);
                    wl += wt; ag += wt * (float)g;
                }
                gn += sl * (ag * q_rcp(wl) - gn);
            }
            float dl = gn - (float)g0;
            int R = qrs(gn + crn), B = qrs(gn + cbn);
            int g1 = qrs((float)r0[2 * bx + 1] + dl), g2 = qrs((float)r1[2 * bx] + dl);
            r0[2 * bx] = (u16)(R < 0 ? 0 : R); r1[2 * bx + 1] = (u16)(B < 0 ? 0 : B);
            r0[2 * bx + 1] = (u16)(g1 < 0 ? 0 : g1); r1[2 * bx] = (u16)(g2 < 0 ? 0 : g2);
        }
    }
}

/* prepare: returns 0 or an error */
static int quad_prepare(const u16* src, int rs, int w, int h, u16* dst, int black) {
    /* w: bits 0-15 width, 16-17 mode, 18 QSC (UW table), 19-22 focus weight 0..15 (0 infinity .. 15 >= 2.48 dpt) */
    int mode = (w >> 16) & 3, qsc = (w >> 18) & 1; float fw = (float)((w >> 19) & 15) / 15.f;
    qj.dnc = (float)((w >> 23) & 7) * 0.1f; qj.dnl = (float)((w >> 26) & 7) * 0.05f; if (mode == 1) qj.dnc = qj.dnl = 0;
    if (mode == 2) { qsc = 0; qj.dnc = qj.dnl = 0; }   /* P297: vivo-remosaiced Bayer: no quad correction / denoise */
    w &= 0xffff; qj.mode = mode; qj.qsc = 0;
    if (w > OW || h > OH || w < 16 || h < 16 || (w & 3) || (h & 3)) return 20;
    if (mode != 2)
    /* guard: the HAL may ignore forceSensorMode and send a normal (remosaiced) Bayer frame.
       Quad: neighbours (same 2x2 block colour) match better than pixels 2 apart; Bayer: the reverse
       (probe: quad 0.59, Bayer 6.2). Reject clear Bayer so GCam keeps the original frame. */
    {
        i64 s1 = 0, s2 = 0; int rsw = rs / 2;
        for (int y = 64; y < h - 64; y += 97) {
            const u16* r0 = src + (i64)y * rsw; const u16* r1 = r0 + rsw; const u16* r2 = r1 + rsw;
            for (int x = 64; x < w - 64; x += 89) {
                int p = r0[x];
                s1 += q_abs(p - r0[x + 1]) + q_abs(p - r1[x]);
                s2 += q_abs(p - r0[x + 2]) + q_abs(p - r2[x]);
            }
        }
        if (s1 * 2 > s2 * 3) return 30;
    }
    i64 need = (i64)w * h;
    if (q_cap < need) {
        q_green = (u16*)q_mmap(need * 2); q_diff = (short*)q_mmap(need * 2 + need / 4 + (1 << 20));
        if (!q_green || !q_diff) { q_cap = 0; return 21; }
        q_cap = need;
    }
    q_build_taps();
    qj.src = src; qj.rsw = rs / 2; qj.w = w; qj.h = h; qj.dst = dst; qj.black = (float)black;
    if (qsc) {                                     /* corrected copy of the source, then the remosaic reads it */
        if (q_corr_cap < need) { q_corr = (u16*)q_mmap(need * 2); if (!q_corr) { q_corr_cap = 0; return 22; } q_corr_cap = need; }
        for (int p = 0; p < 4; ++p) for (int y = 0; y < QSC_GY; ++y) for (int x = 0; x < QSC_GX; ++x)
            q_qtab[p][y][x] = (1.f - fw) * qsc_uw_inv[0][p][y][x] + fw * qsc_uw_inv[1][p][y][x];
        qj.qsc = 1; qj.osrc = src; qj.orsw = rs / 2;
        __atomic_store_n(&qj.nextQ, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneQ, 0, __ATOMIC_SEQ_CST);
    }
    qj.nbands = (h + QB - 1) / QB;
    __atomic_store_n(&qj.nextA, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneA, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.nextM, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneM, 0, __ATOMIC_SEQ_CST);
    __atomic_store_n(&qj.nextC, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneC, 0, __ATOMIC_SEQ_CST);
    __atomic_store_n(&qj.nextD1, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneD1, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.nextD2, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneD2, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.nextD3, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.doneD3, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&qj.nextD4, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&q_doneD4, 0, __ATOMIC_SEQ_CST);
    /* padding: columns w..OW-1 and rows h..OH-1 copied from the source buffer (as the HAL delivered it) */
    for (int y = 0; y < OH; ++y) {
        const u16* s = src + (i64)y * qj.rsw; u16* d = dst + (i64)y * OW;
        if (y < h) { for (int x = w; x < OW; ++x) d[x] = s[x]; }
        else for (int x = 0; x < OW; ++x) d[x] = s[x];
    }
    if (qj.qsc) { qj.src = q_corr; qj.rsw = w; }
    return 0;
}
/* QSC pass: rows y0..y1 of the original source -> q_corr, (v - black) * inverse gain (bilinear over region centres),
   clipped pixels (>= 1020) left as they are */
static void q_qscrow(int y0, int y1) {
    int w = qj.w, h = qj.h, blk = (int)(qj.black + 0.5f), hw = w >> 1;
    int G[OW];                                    /* per row: 16.16 inverse gain of every pixel, x-parity interleaved */
    for (int y = y0; y < y1; ++y) {
        float yy = ((float)(y >> 1) + 0.5f) * QSC_GY / (float)(h >> 1) - 0.5f;
        if (yy < 0) yy = 0; if (yy > QSC_GY - 1) yy = QSC_GY - 1;
        int y0i = (int)yy; if (y0i > QSC_GY - 2) y0i = QSC_GY - 2; float fy = yy - (float)y0i;
        int py = (y & 1) << 1;
        for (int px = 0; px < 2; ++px) {
            const float (*t)[QSC_GX] = q_qtab[py | px]; float col[QSC_GX];
            for (int c = 0; c < QSC_GX; ++c) col[c] = t[y0i][c] + fy * (t[y0i + 1][c] - t[y0i][c]);
            for (int i = 0; i < hw; ++i) {
                float xx = ((float)i + 0.5f) * QSC_GX / (float)hw - 0.5f;
                if (xx < 0) xx = 0; if (xx > QSC_GX - 1) xx = QSC_GX - 1;
                int c0 = (int)xx; if (c0 > QSC_GX - 2) c0 = QSC_GX - 2;
                G[2 * i + px] = (int)((col[c0] + (xx - (float)c0) * (col[c0 + 1] - col[c0])) * 65536.f + 0.5f);
            }
        }
        const u16* s = qj.osrc + (i64)y * qj.orsw; u16* d = q_corr + (i64)y * w;
        for (int x = 0; x < w; ++x) {
            int v = s[x];
            if (v >= 1020) { d[x] = (u16)v; continue; }
            int o = blk + (int)(((long long)(v - blk) * G[x] + 32768) >> 16);
            d[x] = (u16)(o < 0 ? 0 : o > 65535 ? 65535 : o);
        }
    }
}
/* quad binning (high ISO): each 2x2 same-colour block -> its mean (4-pixel average, half the noise), one grid per
   colour at the block centres; the Bayer output samples its colour's grid bilinearly (a 12.5 MP image, upsampled to
   50 MP). Grids live in the q_green scratch (as floats). */
static float* q_grid(int c) { int gw = qj.w >> 2, gh = qj.h >> 2; return (float*)(void*)q_green + (i64)c * gw * gh; }
static void q_binA(int y0, int y1) {               /* block rows y0/4 .. y1/4 */
    int gw = qj.w >> 2; float* g0 = q_grid(0); float* g1 = q_grid(1); float* g2 = q_grid(2); float* g3 = q_grid(3);
    for (int j = y0 >> 2; j < (y1 >> 2); ++j) {
        const u16* r0 = qj.src + (i64)(4 * j) * qj.rsw; const u16* r1 = r0 + qj.rsw;
        const u16* r2 = r1 + qj.rsw; const u16* r3 = r2 + qj.rsw;
        for (int i = 0; i < gw; ++i) {
            int x = 4 * i; i64 o = (i64)j * gw + i;
            g0[o] = 0.25f * ((float)r0[x] + r0[x + 1] + r1[x] + r1[x + 1]);
            g1[o] = 0.25f * ((float)r0[x + 2] + r0[x + 3] + r1[x + 2] + r1[x + 3]);
            g2[o] = 0.25f * ((float)r2[x] + r2[x + 1] + r3[x] + r3[x + 1]);
            g3[o] = 0.25f * ((float)r2[x + 2] + r2[x + 3] + r3[x + 2] + r3[x + 3]);
        }
    }
}
static void q_binC(int y0, int y1) {
    int w = qj.w, gw = qj.w >> 2, gh = qj.h >> 2;
    for (int y = y0; y < y1; ++y) {
        u16* d = qj.dst + (i64)y * OW; int py = y & 1;
        for (int px = 0; px < 2; ++px) {
            int c = py * 2 + px; const float* g = q_grid(c);
            float oy = py ? 2.5f : 0.5f, ox = px ? 2.5f : 0.5f;
            float v = ((float)y - oy) * 0.25f; int j0 = (int)(v < 0 ? -1 : v); if (v < 0) { j0 = 0; v = 0; }
            if (j0 > gh - 2) { j0 = gh - 2; if (v > gh - 1) v = (float)(gh - 1); }
            float fv = v - (float)j0; const float* a = g + (i64)j0 * gw; const float* b = a + gw;
            for (int x = px; x < w; x += 2) {
                float u = ((float)x - ox) * 0.25f; int i0;
                if (u < 0) { i0 = 0; u = 0; } else i0 = (int)u;
                if (i0 > gw - 2) { i0 = gw - 2; if (u > gw - 1) u = (float)(gw - 1); }
                float fu = u - (float)i0;
                float t = a[i0] + fu * (a[i0 + 1] - a[i0]), bb = b[i0] + fu * (b[i0 + 1] - b[i0]);
                d[x] = qround(t + fv * (bb - t));
            }
        }
    }
}
/* XR remosaic (written for this project, 2026-11-26): quad 2x2-block CFA -> Bayer RGGB, two passes.
   pass G: a full-resolution green plane (q_green). At an R/B quad pixel the nearest greens on each axis are 1 px and
   2 px away (other side): linear estimate 2/3 near + 1/3 far per axis; the two axis estimates are blended by the
   inverse of their local gradient (green step + own-colour step to the partner pixel of the 2x2 block).
   pass C: a site of its own quad colour keeps the raw sample; a G site takes the green plane; an R/B site = green +
   the colour difference (raw - green, mean over each 2x2 block of that colour), bilinear between the block centres.
   Mode 2 and 3 of quad_prepare both select it. */
/* P297: mode 2 = the frame is already Bayer (vivo's own remosaic, SR at 25 MP): plain copy, then the pre-merge and the
   50 -> 25 MP resample run as for ER. (Mode 2/3 used to be the XR remosaic, retired in P293.) */
static void q_copy(int y0, int y1) {
    for (int y = y0; y < y1; ++y) {
        const u16* s = qj.src + (i64)y * qj.rsw; u16* d = qj.dst + (i64)y * OW;
        for (int x = 0; x < qj.w; ++x) d[x] = s[x];
    }
}
static void q_rem(void) {
    int nb = qj.nbands, b;
    if (qj.qsc) {
        while ((b = __atomic_fetch_add(&qj.nextQ, 1, __ATOMIC_SEQ_CST)) < nb) {
            int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
            q_qscrow(y0, y1);
            __atomic_fetch_add(&qj.doneQ, 1, __ATOMIC_SEQ_CST);
        }
        while (__atomic_load_n(&qj.doneQ, __ATOMIC_ACQUIRE) < nb) {
#ifdef __aarch64__
            __asm__ volatile("yield");
#endif
        }
    }
    if (qj.mode == 2) {                           /* P297: already Bayer (SR 25 MP): copy */
        while ((b = __atomic_fetch_add(&qj.nextC, 1, __ATOMIC_SEQ_CST)) < nb) {
            int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
            q_copy(y0, y1); __atomic_fetch_add(&qj.doneC, 1, __ATOMIC_SEQ_CST);
        }
        return;
    }
    if (qj.mode == 1) {                           /* bin */
        while ((b = __atomic_fetch_add(&qj.nextA, 1, __ATOMIC_SEQ_CST)) < nb) {
            int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
            q_binA(y0, y1);
            __atomic_fetch_add(&qj.doneA, 1, __ATOMIC_SEQ_CST);
        }
        while (__atomic_load_n(&qj.doneA, __ATOMIC_ACQUIRE) < nb) {
#ifdef __aarch64__
            __asm__ volatile("yield");
#endif
        }
        while ((b = __atomic_fetch_add(&qj.nextC, 1, __ATOMIC_SEQ_CST)) < nb) {
            int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
            q_binC(y0, y1);
        }
        return;
    }
    while ((b = __atomic_fetch_add(&qj.nextA, 1, __ATOMIC_SEQ_CST)) < nb) {
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_passA(y0 / 2, (y1 + 1) / 2);
        __atomic_fetch_add(&qj.doneA, 1, __ATOMIC_SEQ_CST);
    }
    while (__atomic_load_n(&qj.doneA, __ATOMIC_ACQUIRE) < nb) {
#ifdef __aarch64__
        __asm__ volatile("yield");
#endif
    }
    while ((b = __atomic_fetch_add(&qj.nextM, 1, __ATOMIC_SEQ_CST)) < nb) {
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_passM(y0 / 2, (y1 + 1) / 2);
        __atomic_fetch_add(&qj.doneM, 1, __ATOMIC_SEQ_CST);
    }
    while (__atomic_load_n(&qj.doneM, __ATOMIC_ACQUIRE) < nb) {
#ifdef __aarch64__
        __asm__ volatile("yield");
#endif
    }
    while ((b = __atomic_fetch_add(&qj.nextC, 1, __ATOMIC_SEQ_CST)) < nb) {
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_passC(y0, y1); __atomic_fetch_add(&qj.doneC, 1, __ATOMIC_SEQ_CST);
    }
}
static void q_wait(volatile int* c, int n) {
    while (__atomic_load_n(c, __ATOMIC_ACQUIRE) < n) {
#ifdef __aarch64__
        __asm__ volatile("yield");
#endif
    }
}
static void quad_work(void) {
    int nb = qj.nbands, b;
    q_rem();
    if (qj.mode == 1 || (qj.dnc <= 0 && qj.dnl <= 0)) return;
    q_wait(&qj.doneC, nb);
    while ((b = __atomic_fetch_add(&qj.nextD1, 1, __ATOMIC_SEQ_CST)) < nb) {
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_dn1(y0 / 2, y1 / 2); __atomic_fetch_add(&qj.doneD1, 1, __ATOMIC_SEQ_CST);
    }
    q_wait(&qj.doneD1, nb);
    while ((b = __atomic_fetch_add(&qj.nextD2, 1, __ATOMIC_SEQ_CST)) < nb) {      /* QB rows = QB/4 half rows */
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_dn2(y0 / 4, y1 / 4); __atomic_fetch_add(&qj.doneD2, 1, __ATOMIC_SEQ_CST);
    }
    q_wait(&qj.doneD2, nb);
    while ((b = __atomic_fetch_add(&qj.nextD3, 1, __ATOMIC_SEQ_CST)) < nb) {
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_dn3(y0 / 4, y1 / 4); __atomic_fetch_add(&qj.doneD3, 1, __ATOMIC_SEQ_CST);
    }
    q_wait(&qj.doneD3, nb);
    while ((b = __atomic_fetch_add(&qj.nextD4, 1, __ATOMIC_SEQ_CST)) < nb) {
        int y0 = b * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
        q_dn4(y0 / 2, y1 / 2); __atomic_fetch_add(&q_doneD4, 1, __ATOMIC_SEQ_CST);     /* P246: merge waits for it */
    }
}
#undef RAW
