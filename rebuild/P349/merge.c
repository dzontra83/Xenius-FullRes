/* P246 burst merge (test of the SCAMERA idea: the clean look comes from merging the burst ourselves, not from a
   neural network). Runs once per 50 MP burst, on the LAST frame, after its remosaic, on the same worker threads
   (N.w) as the remosaic. Input: the remosaiced Bayer outputs of every frame of the burst (our pool buffers, they stay
   alive until GCam has processed the shot). Output: one robust average, written into EVERY frame of the burst, so
   GCam's own HDR+ merge only sees identical frames (its merge is then a no-op) and does tone/colour/finish as usual.

   1. pyramid  L1 = 8x8 px block means of every frame, L0 = 2x2 cell sums of the reference (frame 0)
   2. global   shift per frame on L2 (L1/4, +-8) then L1 (+-4)
   3. tiles    64x64 px tiles: L1 search +-2 around the global shift, then L0 (cells = 2 px, keeps the CFA phase) +-2
   4. merge    per 2x2 cell and frame: weight from the 3x3-cell mean difference to the reference against the burst's
               measured noise (nz fit, var = S x + O): 1 below K sigma, falling off fast above (moving things keep
               the reference); every pixel = weighted mean of the reference and the aligned frames
   5. copy     the result into every frame buffer
   This file is GPL-3.0 like the rest of libtbin. */
#define MG_MAXF 16
#ifndef MG_REL
#define MG_REL 0.02f
#endif
#ifndef MG_HYB
#define MG_HYB 1
#endif
#ifndef MG_TREJ
#define MG_TREJ 2.5f
#endif
#ifndef MG_WSM
#define MG_WSM 1
#endif
#ifndef MG_SHP
#define MG_SHP 0.4f
#endif
#ifndef MG_LOWT
#define MG_LOWT 0.5f
#endif
#ifndef MG_KR
#define MG_KR 0
#endif
#ifndef MG_KS
#define MG_KS 0.6f
#endif
#ifndef MG_REFINE
#define MG_REFINE 0
#endif
#ifndef MG_AFFINE
#define MG_AFFINE 1
#endif
#ifndef MG_SUB
#define MG_SUB 1
#endif
#ifndef MG_FINE
#define MG_FINE 1
#endif
#define MG_T 64
#define MG_TX 128
#define MG_TY 96
static double nzS, nzO; static int nzfit;               /* last burst noise fit (nz_measure) */
static int pm_night;                                    /* P261: output scale x256 (0/256 = none), from the request hook */
#define PM_MAXX 48
static u16* pm_xreg[PM_MAXX]; static int pm_nx;             /* P284: frames past MG_MAXF */
static int pm_ds, pm_lastdim;                           /* P271: 25 MP downscale on (Motion test); last output w << 16 | h */
static struct {
    int total, n, K10, w, h, active, w1, h1, w0, h0, tx, ty;
    u16* buf[MG_MAXF]; u16* out;
    volatile int nextL, doneL, g, nextA, doneA, nextB, doneB, nextC;
    float va, vb;                                         /* var(code) = va * (v - 64) + vb */
    int gdx[MG_MAXF], gdy[MG_MAXF], gfx[MG_MAXF], gfy[MG_MAXF];
    volatile int g2, nextA2, doneA2;
    float wsum[MG_TY]; int wcnt[MG_TY]; int rej[MG_TY];
    i64 t0;
} mg;
static u16* mg_L1; static u16* mg_L0;
static short mg_sh[MG_MAXF][2][MG_TX * MG_TY];
static int mg_L2[MG_MAXF][256 * 192];
static char mg_txt[320];
static void mg_crinit(void);
static float mg_twx[MG_TX * MG_TY], mg_twy[MG_TX * MG_TY];

static i64 mg_ms(void) {
#ifdef HOST_TEST
    return 0;
#else
    i64 ts[2] = {0, 0};
    register long x0 __asm__("x0") = 1; register long x1 __asm__("x1") = (long)ts; register long x8 __asm__("x8") = 113;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
    return ts[0] * 1000 + ts[1] / 1000000;
#endif
}
static int q_isbusy(const void* p) { for (int i = 0; i < QPOOL; ++i) if (q_pool[i] == p) return q_busy[i]; return 0; }
static void mg_put(char** p, const char* s) { while (*s && *p < mg_txt + sizeof(mg_txt) - 12) *(*p)++ = *s++; }
static void mg_int(char** p, i64 v) { char t[24]; int n = 0; if (v < 0) { *(*p)++ = '-'; v = -v; } do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v); while (n) *(*p)++ = t[--n]; }
static void mg_say(const char* s) { char* o = mg_txt; mg_put(&o, s); *o = 0; }

/* N.n(frames, K x 10): a 50 MP burst of n frames starts */
static void mg_begin(int n, int k10) {
    mg.active = 0; mg.n = 0; mg.total = (n >= 2 && n <= MG_MAXF) ? n : 0;
    mg.K10 = k10 < 5 ? 25 : k10;
}
/* after a successful quad_prepare (frame's remosaic set up, not yet run) */
static void mg_frame(u16* dst) {
    if (mg.total < 2 || qj.mode == 1) { mg.total = 0; return; }
    if (mg.n == 0) { mg.w = qj.w; mg.h = qj.h; }
    else if (qj.w != mg.w || qj.h != mg.h) { mg.total = 0; mg_say("merge off: size changed"); return; }
    if (mg.n >= MG_MAXF) { mg.total = 0; return; }
    mg.buf[mg.n++] = dst;
    if (mg.n < mg.total) return;
    mg.total = 0;                                          /* this burst is done either way */
    for (int k = 0; k < mg.n - 1; ++k) if (!q_isbusy(mg.buf[k])) { mg_say("merge off: a frame was already released"); return; }
    if (!nzfit) { mg_say("merge off: no noise fit"); return; }
    mg.w1 = mg.w / 8; mg.h1 = mg.h / 8; mg.w0 = mg.w / 2; mg.h0 = mg.h / 2;
    mg.tx = (mg.w + MG_T - 1) / MG_T; mg.ty = (mg.h + MG_T - 1) / MG_T;
    if (mg.tx > MG_TX || mg.ty > MG_TY || mg.w1 / 4 > 256 || mg.h1 / 4 > 192) { mg_say("merge off: too big"); return; }
    if (!mg_L1) mg_L1 = (u16*)q_mmap((i64)MG_MAXF * 1024 * 768 * 2);
    if (!mg_L0) mg_L0 = (u16*)q_mmap((i64)4096 * 3072 * 2);
    if (!mg_L1 || !mg_L0) { mg_say("merge off: no memory"); return; }
    mg_crinit();
    mg.out = (u16*)q_acquire(); if (!mg.out) { mg_say("merge off: no output buffer"); return; }
    double S = nzS, O = nzO;
    mg.va = (float)(S * 959.0); mg.vb = (float)(O * 959.0 * 959.0);
    if (mg.va < 0.05f) mg.va = 0.05f;
    if (mg.vb < 0.25f) mg.vb = 0.25f;
    mg.g2 = mg.nextA2 = mg.doneA2 = 0;
    mg.nextL = mg.doneL = mg.g = mg.nextA = mg.doneA = mg.nextB = mg.doneB = mg.nextC = 0;
    for (int i = 0; i < MG_TY; ++i) { mg.wsum[i] = 0; mg.wcnt[i] = 0; mg.rej[i] = 0; }
    mg.t0 = 0;
    __atomic_store_n(&mg.active, 1, __ATOMIC_SEQ_CST);
}

/* 1: L1 row r of every frame (+ L0 rows 4r..4r+3 of the reference) */
static void mg_rowL(int r) {
    int cs[8192];
    int w = mg.w, w1 = mg.w1;
    for (int k = 0; k < mg.n; ++k) {
        const u16* b = mg.buf[k] + (i64)(8 * r) * OW;
        for (int x = 0; x < w; ++x) cs[x] = 0;
        for (int j = 0; j < 8; ++j) { const u16* s = b + (i64)j * OW; for (int x = 0; x < w; ++x) cs[x] += s[x]; }
        u16* o = mg_L1 + (i64)k * 1024 * 768 + (i64)r * w1;
        for (int c = 0; c < w1; ++c) { int s = 0; for (int i = 0; i < 8; ++i) s += cs[8 * c + i]; o[c] = (u16)(s >> 4); }
    }
    for (int j = 0; j < 4; ++j) {
        int y = 4 * r + j; const u16* s0 = mg.buf[0] + (i64)(2 * y) * OW; const u16* s1 = s0 + OW;
        u16* o = mg_L0 + (i64)y * mg.w0;
        for (int x = 0; x < mg.w0; ++x) o[x] = (u16)(s0[2 * x] + s0[2 * x + 1] + s1[2 * x] + s1[2 * x + 1]);
    }
}
static inline int mg_cl(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
#define L1P(k) (mg_L1 + (i64)(k) * 1024 * 768)
/* 2: global shift per frame (single thread) */
static void mg_global(void) {
    int w2 = mg.w1 / 4, h2 = mg.h1 / 4, w1 = mg.w1, h1 = mg.h1;
    for (int k = 0; k < mg.n; ++k) {
        const u16* L = L1P(k);
        for (int y = 0; y < h2; ++y) for (int x = 0; x < w2; ++x) {
            int s = 0; for (int j = 0; j < 4; ++j) for (int i = 0; i < 4; ++i) s += L[(i64)(4 * y + j) * w1 + 4 * x + i];
            mg_L2[k][y * w2 + x] = s;
        }
    }
    mg.gdx[0] = mg.gdy[0] = 0;
    for (int k = 1; k < mg.n; ++k) {
        i64 best = -1; int bx = 0, by = 0;
        for (int sy = -8; sy <= 8; ++sy) for (int sx = -8; sx <= 8; ++sx) {
            i64 sad = 0;
            for (int y = 10; y < h2 - 10; ++y) for (int x = 10; x < w2 - 10; ++x) {
                int d = mg_L2[0][y * w2 + x] - mg_L2[k][(y + sy) * w2 + x + sx]; sad += d < 0 ? -d : d;
            }
            if (best < 0 || sad < best) { best = sad; bx = sx; by = sy; }
        }
        const u16* R = L1P(0); const u16* L = L1P(k); best = -1; int cx = 4 * bx, cy = 4 * by, fx = cx, fy = cy;
        for (int sy = cy - 4; sy <= cy + 4; ++sy) for (int sx = cx - 4; sx <= cx + 4; ++sx) {
            i64 sad = 0;
            for (int y = 48; y < h1 - 48; y += 2) for (int x = 48; x < w1 - 48; x += 2) {
                int d = R[(i64)y * w1 + x] - L[(i64)(y + sy) * w1 + x + sx]; sad += d < 0 ? -d : d;
            }
            if (best < 0 || sad < best) { best = sad; fx = sx; fy = sy; }
        }
        mg.gdx[k] = fx; mg.gdy[k] = fy;
    }
}
/* 3: tile shifts of tile row ty, in px (sub-cell from a parabola through the cell SAD) */
static void mg_tilesA(int ty) {
    int w1 = mg.w1, h1 = mg.h1, w0 = mg.w0, h0 = mg.h0;
    const u16* R = L1P(0);
    int P[36 * 36]; i64 sd[5][5];
    for (int tx = 0; tx < mg.tx; ++tx) {
        int t = ty * MG_TX + tx;
        mg_sh[0][0][t] = mg_sh[0][1][t] = 0;
        int c1 = tx * 8, r1 = ty * 8, c0 = tx * 32, r0 = ty * 32;
        for (int k = 1; k < mg.n; ++k) {
            const u16* L = L1P(k);
            i64 best = -1; int bx = mg.gdx[k], by = mg.gdy[k];
            for (int sy = mg.gdy[k] - 2; sy <= mg.gdy[k] + 2; ++sy) for (int sx = mg.gdx[k] - 2; sx <= mg.gdx[k] + 2; ++sx) {
                i64 sad = 0;
                for (int y = r1; y < r1 + 8 && y < h1; ++y) for (int x = c1; x < c1 + 8 && x < w1; ++x) {
                    int d = R[(i64)y * w1 + x] - L[(i64)mg_cl(y + sy, 0, h1 - 1) * w1 + mg_cl(x + sx, 0, w1 - 1)]; sad += d < 0 ? -d : d;
                }
                sad += (i64)((sx - mg.gdx[k]) * (sx - mg.gdx[k]) + (sy - mg.gdy[k]) * (sy - mg.gdy[k])) * 8;   /* flat tiles: global */
                if (best < 0 || sad < best) { best = sad; bx = sx; by = sy; }
            }
            int cx = 4 * bx, cy = 4 * by;                     /* cells */
            const u16* B = mg.buf[k];
            for (int j = 0; j < 36; ++j) for (int i = 0; i < 36; ++i) {
                int X = 2 * mg_cl(c0 + cx - 2 + i, 0, w0 - 1), Y = 2 * mg_cl(r0 + cy - 2 + j, 0, h0 - 1);
                const u16* s = B + (i64)Y * OW + X; P[j * 36 + i] = s[0] + s[1] + s[OW] + s[OW + 1];
            }
            best = -1; int fx = 0, fy = 0;
            for (int dy = -2; dy <= 2; ++dy) for (int dx = -2; dx <= 2; ++dx) {
                i64 sad = 0;
                for (int j = 0; j < 32 && r0 + j < h0; ++j) {
                    const u16* rr = mg_L0 + (i64)(r0 + j) * w0; const int* pp = P + (j + 2 + dy) * 36 + 2 + dx;
                    for (int i = j & 1; i < 32 && c0 + i < w0; i += 2) { int d = rr[c0 + i] - pp[i]; sad += d < 0 ? -d : d; }
                }
                sd[dy + 2][dx + 2] = sad;
                sad += (i64)(dx * dx + dy * dy) * 4;
                if (best < 0 || sad < best) { best = sad; fx = dx; fy = dy; }
            }
            float ox = 0, oy = 0;                             /* parabola, cells */
            if (fx > -2 && fx < 2) { float l = (float)sd[fy + 2][fx + 1], c = (float)sd[fy + 2][fx + 2], r = (float)sd[fy + 2][fx + 3], den = l - 2 * c + r;
                if (den > 0) { ox = 0.5f * (l - r) / den; ox = ox < -0.5f ? -0.5f : (ox > 0.5f ? 0.5f : ox); } }
            if (fy > -2 && fy < 2) { float u = (float)sd[fy + 1][fx + 2], c = (float)sd[fy + 2][fx + 2], d = (float)sd[fy + 3][fx + 2], den = u - 2 * c + d;
                if (den > 0) { oy = 0.5f * (u - d) / den; oy = oy < -0.5f ? -0.5f : (oy > 0.5f ? 0.5f : oy); } }
            float px = 2.f * ((float)(cx + fx) + (MG_SUB ? ox : 0)), py = 2.f * ((float)(cy + fy) + (MG_SUB ? oy : 0));
            mg_sh[k][0][t] = (short)qrs(px); mg_sh[k][1][t] = (short)qrs(py);
        }
    }
}
static float mg_sqrt(float x) {                        /* x > 0 */
    union { float f; u32 i; } u; u.f = x; u.i = 0x1fbd1df5 + (u.i >> 1);
    float y = u.f; y = 0.5f * (y + x / y); y = 0.5f * (y + x / y); return 0.5f * (y + x / y);
}
/* 3b: per frame the median tile shift (px) = the fine global shift (single thread) */
static short mg_tmp[MG_TX * MG_TY];
static int mg_median(int k, int c) {
    int n = 0;
    for (int ty = 0; ty < mg.ty; ++ty) for (int tx = 0; tx < mg.tx; ++tx) mg_tmp[n++] = mg_sh[k][c][ty * MG_TX + tx];
    int lo = 0, hi = n - 1, q = n / 2;
    while (lo < hi) { short pv = mg_tmp[(lo + hi) >> 1]; int i = lo, j = hi;
        while (i <= j) { while (mg_tmp[i] < pv) ++i; while (mg_tmp[j] > pv) --j; if (i <= j) { short t = mg_tmp[i]; mg_tmp[i] = mg_tmp[j]; mg_tmp[j] = t; ++i; --j; } }
        if (q <= j) hi = j; else if (q >= i) lo = i; else break; }
    return mg_tmp[q];
}
static void mg_global2(void) { for (int k = 1; k < mg.n; ++k) { mg.gfx[k] = mg_median(k, 0); mg.gfy[k] = mg_median(k, 1); } }
/* 3c: final tile shifts: L0 search +-MG_R cells around the fine global shift, a noise-scaled cost per cell of
   distance (a flat or noisy tile stays on the global shift, a tile with real local motion moves), sub-cell parabola */
#ifndef MG_R
#define MG_R 4
#endif
#ifndef MG_LAM
#define MG_LAM 1.0f
#endif
static void mg_tilesA2(int ty) {
    int w0 = mg.w0, h0 = mg.h0;
    enum { PW = 32 + 2 * MG_R + 2 };
    int P[PW * PW]; float sd[2 * MG_R + 1][2 * MG_R + 1]; float sq[2 * MG_R + 1][2 * MG_R + 1];
    for (int tx = 0; tx < mg.tx; ++tx) {
        int t = ty * MG_TX + tx, c0 = tx * 32, r0 = ty * 32;
        /* noise of a 2x2 cell sum difference at the tile's level */
        i64 ls = 0; int ln = 0;
        for (int j = 0; j < 32 && r0 + j < h0; j += 4) for (int i = 0; i < 32 && c0 + i < w0; i += 4) { ls += mg_L0[(i64)(r0 + j) * w0 + c0 + i]; ++ln; }
        float v = ln ? (float)ls / ln * 0.25f : 64.f;
        float var = mg.va * (v > 64.f ? v - 64.f : 0.f) + mg.vb;
        float pen = MG_LAM * mg_sqrt(512.f * 16.f * var);
        for (int k = 1; k < mg.n; ++k) {
            int gx = mg.gfx[k] >> 1, gy = mg.gfy[k] >> 1;      /* cells (floor) */
            const u16* B = mg.buf[k];
            for (int j = 0; j < PW; ++j) for (int i = 0; i < PW; ++i) {
                int X = 2 * mg_cl(c0 + gx - MG_R - 1 + i, 0, w0 - 1), Y = 2 * mg_cl(r0 + gy - MG_R - 1 + j, 0, h0 - 1);
                const u16* s = B + (i64)Y * OW + X; P[j * PW + i] = s[0] + s[1] + s[OW] + s[OW + 1];
            }
            float best = -1; int fx = 0, fy = 0;
            float ex = (float)(mg.gfx[k] - 2 * gx) * 0.5f, ey = (float)(mg.gfy[k] - 2 * gy) * 0.5f;   /* global's sub-cell part */
            for (int dy = -MG_R; dy <= MG_R; ++dy) for (int dx = -MG_R; dx <= MG_R; ++dx) {
                i64 sad = 0, ssd = 0;
                int jn = h0 - r0 < 32 ? h0 - r0 : 32, in = w0 - c0 < 32 ? w0 - c0 : 32;   /* P267: bounds hoisted, */
                for (int j = 0; j < jn; ++j) {                                                  /* int row sums (exact) */
                    const u16* rr = mg_L0 + (i64)(r0 + j) * w0 + c0; const int* pp = P + (j + MG_R + 1 + dy) * PW + MG_R + 1 + dx;
                    int sa = 0, sq2 = 0;
                    for (int i = j & 1; i < in; i += 2) { int d = rr[i] - pp[i]; sa += d < 0 ? -d : d; sq2 += d * d; }
                    sad += sa; ssd += sq2;
                }
                sd[dy + MG_R][dx + MG_R] = (float)sad; sq[dy + MG_R][dx + MG_R] = (float)ssd;
                float ax = (float)dx - ex, ay = (float)dy - ey;
                float c = (float)sad + pen * ((ax < 0 ? -ax : ax) + (ay < 0 ? -ay : ay));
                if (best < 0 || c < best) { best = c; fx = dx; fy = dy; }
            }
            float ox = 0, oy = 0; float wxk = 0, wyk = 0;
            if (fx > -MG_R && fx < MG_R) { float l = sq[fy + MG_R][fx + MG_R - 1], c = sq[fy + MG_R][fx + MG_R], r = sq[fy + MG_R][fx + MG_R + 1], den = l - 2 * c + r;
                if (den > 0) { ox = 0.5f * (l - r) / den; ox = ox < -0.5f ? -0.5f : (ox > 0.5f ? 0.5f : ox); wxk = den / (512.f * 16.f * var); } }
            if (fy > -MG_R && fy < MG_R) { float u = sq[fy + MG_R - 1][fx + MG_R], c = sq[fy + MG_R][fx + MG_R], d = sq[fy + MG_R + 1][fx + MG_R], den = u - 2 * c + d;
                if (den > 0) { oy = 0.5f * (u - d) / den; oy = oy < -0.5f ? -0.5f : (oy > 0.5f ? 0.5f : oy); wyk = den / (512.f * 16.f * var); } }
            if (k == 1) { mg_twx[t] = wxk; mg_twy[t] = wyk; }
            mg_sh[k][0][t] = (short)qrs(8.f * ((float)(gx + fx) + ox)); mg_sh[k][1][t] = (short)qrs(8.f * ((float)(gy + fy) + oy));   /* quarter px */
        }
    }
}
/* P250: tile shifts are noisy (+-0.6..0.9 px per tile in the host test) -> per frame an affine model of the shift
   field (x and y separately, weighted by the SAD curvature = texture, 3 reweighted passes rejecting tiles > 1.5 px
   off), its prediction replaces the tile shifts. Local motion that does not fit is left to the robustness weights. */
static int mg_fitn, mg_fitres, mg_lockeep;                              /* log: tiles used, residual rms x100 px */
static int mg_solve3(double A[3][3], double b[3], double x[3]) {
    double m[3][4]; for (int i = 0; i < 3; ++i) { for (int j = 0; j < 3; ++j) m[i][j] = A[i][j]; m[i][3] = b[i]; }
    for (int c = 0; c < 3; ++c) { int p = c; for (int r = c + 1; r < 3; ++r) if ((m[r][c] < 0 ? -m[r][c] : m[r][c]) > (m[p][c] < 0 ? -m[p][c] : m[p][c])) p = r;
        if (m[p][c] == 0) return 0; for (int j = 0; j < 4; ++j) { double t = m[c][j]; m[c][j] = m[p][j]; m[p][j] = t; }
        for (int r = 0; r < 3; ++r) if (r != c) { double f = m[r][c] / m[c][c]; for (int j = 0; j < 4; ++j) m[r][j] -= f * m[c][j]; } }
    for (int i = 0; i < 3; ++i) x[i] = m[i][3] / m[i][i];
    return 1;
}
static void mg_fit(void) {
    mg_lockeep = 0;
    int k = 1; double cf[2][3]; int ok[2] = {0, 0}; double rs = 0; int nr = 0, nu = 0;
    for (int c = 0; c < 2; ++c) {
        const float* tw = c ? mg_twy : mg_twx;
        double lim = 1e30;
        for (int it = 0; it < 3; ++it) {
            double A[3][3] = {{0}}, b[3] = {0}; int n = 0;
            for (int ty = 0; ty < mg.ty; ++ty) for (int tx = 0; tx < mg.tx; ++tx) {
                int t = ty * MG_TX + tx; double w = tw[t]; if (w <= 0.05) continue;
                double X = (tx * MG_T + 32) / 1000.0, Y = (ty * MG_T + 32) / 1000.0, s = mg_sh[k][c][t] / 4.0;
                if (it) { double e = s - (cf[c][0] + cf[c][1] * X + cf[c][2] * Y); if (e * e > lim) continue; }
                if (w > 4) w = 4;
                double v[3] = {1, X, Y};
                for (int i = 0; i < 3; ++i) { b[i] += w * v[i] * s; for (int j = 0; j < 3; ++j) A[i][j] += w * v[i] * v[j]; }
                ++n;
            }
            if (n < 40 || !mg_solve3(A, b, cf[c])) { ok[c] = 0; break; }
            ok[c] = 1; lim = 1.5 * 1.5; if (c == 0) nu = n;
        }
    }
    if (!ok[0] || !ok[1]) { mg_fitn = 0; return; }
    for (int ty = 0; ty < mg.ty; ++ty) for (int tx = 0; tx < mg.tx; ++tx) {
        int t = ty * MG_TX + tx; double X = (tx * MG_T + 32) / 1000.0, Y = (ty * MG_T + 32) / 1000.0;
        double px_ = cf[0][0] + cf[0][1] * X + cf[0][2] * Y, py_ = cf[1][0] + cf[1][1] * X + cf[1][2] * Y;
        double ex = mg_sh[k][0][t] / 4.0 - px_, ey = mg_sh[k][1][t] / 4.0 - py_;
        if (mg_twx[t] > 0.05 && ex * ex < 2.25) { rs += ex * ex; ++nr; }
        if (mg_twy[t] > 0.05 && ey * ey < 2.25) { rs += ey * ey; ++nr; }
        /* P251: a well-textured tile whose own shift is clearly off the model (parallax, local motion) keeps it */
        if (MG_HYB && mg_twx[t] > 0.5f && mg_twy[t] > 0.5f && ex * ex + ey * ey > 0.75 * 0.75 && ex * ex + ey * ey < 16.0) { ++mg_lockeep; continue; }
        mg_sh[k][0][t] = (short)qrs((float)(px_ * 4.0)); mg_sh[k][1][t] = (short)qrs((float)(py_ * 4.0));
    }
    mg_fitn = nu; mg_fitres = nr ? (int)(100.0 * __builtin_sqrt(rs / nr)) : -1;
}
/* P250: frame k sampled at (X + sx/4, Y + sy/4) (shift in quarter px) with the CFA colour of (X, Y): Catmull-Rom over
   the same-colour samples (spacing 2 px), 1/8-sample phases; an exact same-colour position = the sample itself */
static float mg_cr[8][4];
static void mg_crinit(void) {
    for (int f = 0; f < 8; ++f) { float t = f / 8.f, t2 = t * t, t3 = t2 * t;
        mg_cr[f][0] = 0.5f * (-t3 + 2 * t2 - t); mg_cr[f][1] = 0.5f * (3 * t3 - 5 * t2 + 2); mg_cr[f][2] = 0.5f * (-3 * t3 + 4 * t2 + t); mg_cr[f][3] = 0.5f * (t3 - t2); }
}
static inline float mg_smp(const u16* B, int X, int Y, int sxq, int syq) {
    int w = mg.w, h = mg.h, px = X & 1, py = Y & 1;
    int nx_ = 4 * (X - px) + sxq, ny_ = 4 * (Y - py) + syq;           /* in 1/8 of a same-colour sample */
    int iu = nx_ >> 3, fu = nx_ & 7, iv = ny_ >> 3, fv = ny_ & 7;       /* arithmetic shift = floor */
    int xs[4], ys[4], nx, ny; const float* wx; const float* wy; static const float one[4] = {0, 1, 0, 0};
    if (!fu) { xs[0] = mg_cl(2 * iu + px, px, w - 2 + px); nx = 1; wx = one + 1; }
    else { for (int i = 0; i < 4; ++i) xs[i] = mg_cl(2 * (iu - 1 + i) + px, px, w - 2 + px); nx = 4; wx = mg_cr[fu]; }
    if (!fv) { ys[0] = mg_cl(2 * iv + py, py, h - 2 + py); ny = 1; wy = one + 1; }
    else { for (int i = 0; i < 4; ++i) ys[i] = mg_cl(2 * (iv - 1 + i) + py, py, h - 2 + py); ny = 4; wy = mg_cr[fv]; }
    float v = 0;
    for (int j = 0; j < ny; ++j) { const u16* r = B + (i64)ys[j] * OW; float a = 0; for (int i = 0; i < nx; ++i) a += wx[i] * (float)r[xs[i]]; v += wy[j] * a; }
    return v;
}
/* P250: the tile search is cell based (2 px) and its sub-cell parabola is biased toward whole cells (host test:
   0.2-0.4 px). After the affine fit, the whole field is shifted by the quarter-px offset (+-0.75 px, x then y, twice)
   that best matches the reference on the 64 most textured tiles, with the real Catmull-Rom resampling. */
static int mg_refoff[2];
static void mg_refine(void) {
    int sel[64], ns = 0; float sw[64];
    for (int ty = 1; ty < mg.ty - 1; ++ty) for (int tx = 1; tx < mg.tx - 1; ++tx) {
        int t = ty * MG_TX + tx; float w = mg_twx[t] < mg_twy[t] ? mg_twx[t] : mg_twy[t];
        if (w <= 0.05f) continue;
        if (ns < 64) { sel[ns] = t; sw[ns] = w; ++ns; continue; }
        int mi = 0; for (int i = 1; i < 64; ++i) if (sw[i] < sw[mi]) mi = i;
        if (w > sw[mi]) { sel[mi] = t; sw[mi] = w; }
    }
    mg_refoff[0] = mg_refoff[1] = 0;
    if (ns < 8) return;
    int off[2] = {0, 0};
    for (int pass = 0; pass < 4; ++pass) {
        int c = pass & 1; double best = -1; int bo = 0;
        for (int o = -3; o <= 3; ++o) {
            int ox = off[0] + (c == 0 ? o : 0), oy = off[1] + (c == 1 ? o : 0);
            double ssd = 0;
            for (int i = 0; i < ns; ++i) {
                int t = sel[i], tx = t % MG_TX, ty = t / MG_TX, X0 = tx * MG_T + 16, Y0 = ty * MG_T + 16;
                int sx = mg_sh[1][0][t] + ox, sy = mg_sh[1][1][t] + oy;
                for (int y = 0; y < 32; ++y) { const u16* r = mg.buf[0] + (i64)(Y0 + y) * OW + X0;
                    for (int x = 0; x < 32; ++x) { float d = (float)r[x] - mg_smp(mg.buf[1], X0 + x, Y0 + y, sx, sy); ssd += d * d; } }
            }
            if (best < 0 || ssd < best) { best = ssd; bo = o; }
        }
        off[c] += bo;
    }
    for (int ty = 0; ty < mg.ty; ++ty) for (int tx = 0; tx < mg.tx; ++tx) { int t = ty * MG_TX + tx; mg_sh[1][0][t] += off[0]; mg_sh[1][1][t] += off[1]; }
    mg_refoff[0] = off[0]; mg_refoff[1] = off[1];
}
/* P250 kernel merge: instead of interpolating frame k onto the reference grid (which cannot keep detail near the
   same-colour Nyquist), its 2x2 nearest same-colour samples around (X + sx/4, Y + sy/4) are added with Gaussian
   weights of their distance (sigma MG_KS px): a frame whose samples land on the output pixel adds full detail, one in
   between adds mostly noise reduction. Weights are normalised per output pixel over all frames. */
static float mg_kw[9];
static void mg_kinit(void) { for (int f = 0; f <= 8; ++f) { float d = 2.f * f / 8.f; float e = -d * d / (2.f * MG_KS * MG_KS);
    /* exp(e), e in [-11, 0] */ float r = 1.f; float x = e / 64.f; float t = 1.f + x * (1.f + x * (0.5f + x * (1.f / 6.f)));
    for (int i = 0; i < 6; ++i) t = t * t; r = t; mg_kw[f] = r; } }
static inline float mg_kr(const u16* B, int X, int Y, int sxq, int syq, float* ws) {
    int w = mg.w, h = mg.h, px = X & 1, py = Y & 1;
    int nx_ = 4 * (X - px) + sxq, ny_ = 4 * (Y - py) + syq;
    int iu = nx_ >> 3, fu = nx_ & 7, iv = ny_ >> 3, fv = ny_ & 7;
    int x0 = mg_cl(2 * iu + px, px, w - 2 + px), x1 = mg_cl(2 * iu + 2 + px, px, w - 2 + px);
    int y0 = mg_cl(2 * iv + py, py, h - 2 + py), y1 = mg_cl(2 * iv + 2 + py, py, h - 2 + py);
    float ax = mg_kw[fu], bx = mg_kw[8 - fu], ay = mg_kw[fv], by = mg_kw[8 - fv];
    const u16* r0 = B + (i64)y0 * OW; const u16* r1 = B + (i64)y1 * OW;
    *ws = (ax + bx) * (ay + by);
    return ay * (ax * r0[x0] + bx * r0[x1]) + by * (ax * r1[x0] + bx * r1[x1]);
}
/* 4: merge tile row ty into mg.out */
#define MG_PW (MG_T + 4)
static void mg_tilesB(int ty) {
    int w = mg.w, h = mg.h, w0 = mg.w0, h0 = mg.h0;
    float acc[MG_T * MG_T]; float wt[32 * 32]; float F[MG_PW * MG_PW];
    float Pk[34 * 34]; int Pr[34 * 34];
    float K2 = (float)mg.K10 * (float)mg.K10 / 100.f;
    unsigned long long rng = 0x9e3779b97f4a7c15ULL * (unsigned long long)(ty + 1);
    float wtot = 0; int ncell = 0, nrej = 0;
    for (int tx = 0; tx < mg.tx; ++tx) {
        int t = ty * MG_TX + tx, X0 = tx * MG_T, Y0 = ty * MG_T;
        int tw = X0 + MG_T <= w ? MG_T : w - X0, th = Y0 + MG_T <= h ? MG_T : h - Y0;
        int c0 = X0 / 2, r0 = Y0 / 2, cw = tw / 2, ch = th / 2;
        const u16* R = mg.buf[0];
        for (int y = 0; y < th; ++y) for (int x = 0; x < tw; ++x) acc[y * MG_T + x] = R[(i64)(Y0 + y) * OW + X0 + x];
        for (int i = 0; i < 32 * 32; ++i) wt[i] = 1.f;
        for (int j = 0; j < 34; ++j) for (int i = 0; i < 34; ++i)
            Pr[j * 34 + i] = mg_L0[(i64)mg_cl(r0 - 1 + j, 0, h0 - 1) * w0 + mg_cl(c0 - 1 + i, 0, w0 - 1)];
        for (int k = 1; k < mg.n; ++k) {
            int sx = mg_sh[k][0][t], sy = mg_sh[k][1][t];
            const u16* B = mg.buf[k];
            /* frame k resampled onto the tile (+2 px border; outside the image: clamped reference positions) */
            for (int j = 0; j < MG_PW; ++j) for (int i = 0; i < MG_PW; ++i) {
                int X = mg_cl(X0 - 2 + i, (i & 1), w - 2 + (i & 1)), Y = mg_cl(Y0 - 2 + j, (j & 1), h - 2 + (j & 1));
                F[j * MG_PW + i] = mg_smp(B, X, Y, sx, sy);
            }
            for (int j = 0; j < 34; ++j) for (int i = 0; i < 34; ++i) {
                const float* f = F + (2 * j) * MG_PW + 2 * i; Pk[j * 34 + i] = f[0] + f[1] + f[MG_PW] + f[MG_PW + 1];
            }
            for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) {
                float dm = 0;
                for (int j = 0; j < 3; ++j) for (int i = 0; i < 3; ++i) { int o = (cy + j) * 34 + cx + i; dm += Pk[o] - (float)Pr[o]; }
                float v = (float)Pr[(cy + 1) * 34 + cx + 1] * 0.25f;
                float var = mg.va * (v > 64.f ? v - 64.f : 0.f) + mg.vb;
                float z2 = dm * dm / (144.f * var);
                /* fine test: the cell itself (4 px) - a residual misalignment on texture / edges fails here and the
                   reference keeps its detail; flat areas pass and get the full average */
                float d1 = Pk[(cy + 1) * 34 + cx + 1] - (float)Pr[(cy + 1) * 34 + cx + 1];
                float z1 = d1 * d1 / (16.f * var);
                if (MG_FINE && z1 > z2) z2 = z1;
                float wk = 1.f;
                if (z2 > K2) { float q = 1.f + (z2 - K2); wk = 1.f / (q * q); if (wk < 0.01f) { wk = 0; ++nrej; } }
                if (wk <= 0) continue;
                wt[cy * 32 + cx] += wk;
                for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i)
                    acc[(2 * cy + j) * MG_T + 2 * cx + i] += wk * F[(2 * cy + j + 2) * MG_PW + 2 * cx + i + 2];
            }
        }
        for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) { wtot += wt[cy * 32 + cx]; ++ncell; }
        for (int y = 0; y < th; ++y) {
            u16* o = mg.out + (i64)(Y0 + y) * OW + X0;
            for (int x = 0; x < tw; ++x) {
                float v = acc[y * MG_T + x] / wt[(y >> 1) * 32 + (x >> 1)];
                rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
                float d = ((float)(u32)(rng >> 40 & 0xffffff) - (float)(u32)(rng >> 16 & 0xffffff)) * (0.5f / 16777216.f);
                int r = R[(i64)(Y0 + y) * OW + X0 + x];
                int iv = r >= 1020 ? r : (int)(v + d + 0.5f);
                o[x] = (u16)(iv < 0 ? 0 : (iv > 1023 ? 1023 : iv));
            }
        }
    }
    mg.wsum[ty] = wtot; mg.wcnt[ty] = ncell; mg.rej[ty] = nrej;
}
/* 5: rows [y0, y1) of the result into every frame */
static void mg_copy(int y0, int y1) {
    for (int k = 0; k < mg.n; ++k) for (int y = y0; y < y1; ++y) {
        const u16* s = mg.out + (i64)y * OW; u16* d = mg.buf[k] + (i64)y * OW;
        for (int x = 0; x < mg.w; ++x) d[x] = s[x];
#ifdef MG_DBG
#ifndef MG_DBG_SEL
#define MG_DBG_SEL(k) ((k) < mg.n - 1)
#endif
        /* diagnostic build: black 1024 px square in every frame except the last -> visible only if GCam
                   reads the earlier frames after the burst (does it copy them on arrival?) */
        if (MG_DBG_SEL(k) && y >= mg.h / 2 - 512 && y < mg.h / 2 + 512) for (int x = mg.w / 2 - 512; x < mg.w / 2 + 512; ++x) d[x] = 64;
#endif
    }
}
/* every worker thread and the caller, after quad_work */
static void mg_work(void) {
    if (!__atomic_load_n(&mg.active, __ATOMIC_ACQUIRE)) return;
    int nb = qj.nbands, b;
    if (qj.dnc > 0 || qj.dnl > 0) q_wait(&q_doneD4, nb); else q_wait(&qj.doneC, nb);
    { i64 z = 0; i64 now = mg_ms(); __atomic_compare_exchange_n(&mg.t0, &z, now, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST); }
    while ((b = __atomic_fetch_add(&mg.nextL, 1, __ATOMIC_SEQ_CST)) < mg.h1) { mg_rowL(b); __atomic_fetch_add(&mg.doneL, 1, __ATOMIC_SEQ_CST); }
    q_wait(&mg.doneL, mg.h1);
    { int z = 0; if (__atomic_compare_exchange_n(&mg.g, &z, 1, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) { mg_global(); __atomic_store_n(&mg.g, 2, __ATOMIC_SEQ_CST); } }
    q_wait(&mg.g, 2);
    while ((b = __atomic_fetch_add(&mg.nextA, 1, __ATOMIC_SEQ_CST)) < mg.ty) { mg_tilesA(b); __atomic_fetch_add(&mg.doneA, 1, __ATOMIC_SEQ_CST); }
    q_wait(&mg.doneA, mg.ty);
    { int z = 0; if (__atomic_compare_exchange_n(&mg.g2, &z, 1, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) { mg_global2(); __atomic_store_n(&mg.g2, 2, __ATOMIC_SEQ_CST); } }
    q_wait(&mg.g2, 2);
    while ((b = __atomic_fetch_add(&mg.nextA2, 1, __ATOMIC_SEQ_CST)) < mg.ty) { mg_tilesA2(b); __atomic_fetch_add(&mg.doneA2, 1, __ATOMIC_SEQ_CST); }
    q_wait(&mg.doneA2, mg.ty);
    while ((b = __atomic_fetch_add(&mg.nextB, 1, __ATOMIC_SEQ_CST)) < mg.ty) { mg_tilesB(b); __atomic_fetch_add(&mg.doneB, 1, __ATOMIC_SEQ_CST); }
    q_wait(&mg.doneB, mg.ty);
    int nc = (mg.h + 31) / 32;
    while ((b = __atomic_fetch_add(&mg.nextC, 1, __ATOMIC_SEQ_CST)) < nc) { int y0 = b * 32; mg_copy(y0, y0 + 32 > mg.h ? mg.h : y0 + 32); }
}
/* single thread, after every worker returned (tbin_finish) */
static void mg_finish(void) {
    if (!mg.active) return;
    mg.active = 0;
    double ws = 0; i64 nc = 0, nr = 0;
    for (int i = 0; i < mg.ty; ++i) { ws += mg.wsum[i]; nc += mg.wcnt[i]; nr += mg.rej[i]; }
    int mx = 0;
    for (int k = 1; k < mg.n; ++k) { int a = mg.gdx[k] < 0 ? -mg.gdx[k] : mg.gdx[k], c = mg.gdy[k] < 0 ? -mg.gdy[k] : mg.gdy[k]; if (a > mx) mx = a; if (c > mx) mx = c; }
    char* o = mg_txt;
    mg_put(&o, "merge frames="); mg_int(&o, mg.n);
    mg_put(&o, " eff="); mg_int(&o, nc ? (i64)(ws * 100 / nc) : 0); mg_put(&o, "/100");
    mg_put(&o, " rej="); mg_int(&o, nc ? nr * 1000 / (nc * (mg.n - 1)) : 0); mg_put(&o, "/1000");
    mg_put(&o, " gmax="); mg_int(&o, mx * 8); mg_put(&o, "px K="); mg_int(&o, mg.K10);
    mg_put(&o, " ms="); mg_int(&o, mg.t0 ? mg_ms() - mg.t0 : -1);
    *o = 0;
    q_release(mg.out); mg.out = 0;
}

/* ======================= P247: pre-merge =======================
   P246 showed GCam hands every frame to HDR+ right after its conversion (and does not always take the last frame as
   base), so merging on the last frame is too late. P247 merges the WHOLE burst while the FIRST frame is converted:
   all raw 50 MP frames of the shot are already in LMC's props slots then. The helper (Ldvm.o entry) registers their
   buffers (N.p); the first frame's N.q runs: remosaic every frame in turn, align it to frame 0 and add it to a running
   weighted sum; the result goes to frame 0 and to a kept copy, and every later frame of the burst just gets the
   copy (N.q -> copy job). All frames HDR+ receives are identical -> its merge is a no-op. */
static volatile int nz_have_reset; static int pm_lastjob;
#ifndef HOST_TEST
static void nz_measure(const u16* d, int w, int h); static void nz_reset(void);
#else
static void nz_measure(const u16* d, int w, int h) { (void)d; (void)w; (void)h; }
static void nz_reset(void) {}
#endif
#define PM_MAXPH 256
#ifndef PM_SHMIN
#define PM_SHMIN 90
#endif
enum { P_SETUP, P_QSC, P_A, P_M, P_C, P_XG, P_XC, P_D1, P_D2, P_D3, P_D4, P_NZ, P_L0, P_INIT, P_L, P_G, P_TA, P_MED,
       P_TA2, P_ACC, P_FIN, P_COPY, P_SHARP, P_PICK, P_FIT, P_DSH, P_DSV, P_DSC };
static struct {
    int armed, state, nreg, job;              /* state 0 registering, 1 merging, 2 merged copy ready; job 1 merge 2 copy */
    u16* reg[MG_MAXF]; int regrs[MG_MAXF]; int used[MG_MAXF];
    int wbits, h, w, mode, nb, ref, cur, skip, ncopied, nmerged;
    u16* keep; u16* tmp; float* acc; float* wtc;
    int nph; int ph_kind[PM_MAXPH], ph_frame[PM_MAXPH], ph_n[PM_MAXPH], ph_start[PM_MAXPH];
    volatile int next, done[PM_MAXPH]; int total;
    i64 t0;
    i64 lowdn; volatile int trej;
    int fitn, fitres, nfit, refx, refy, lockeep;
    int order[MG_MAXF], nuse; i64 shp[MG_MAXF][16]; int shrel[MG_MAXF];
} pm;
static void pm_munmap(void* p, i64 n) {
#ifndef HOST_TEST
    if (!p) return;
    register long x0 __asm__("x0") = (long)p; register long x1 __asm__("x1") = n; register long x8 __asm__("x8") = 215;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x8) : "memory");
#endif
}
#define PM_ACC ((i64)OW * OH * 4)
#define PM_WTC (MG_KR ? (i64)OW * OH * 4 : (i64)4096 * 3072 * 4)
static void pm_free(void) {
    if (pm.keep && pm.keep != pm.tmp) q_release(pm.keep);
    if (pm.tmp) q_release(pm.tmp);
    pm.keep = 0; pm.tmp = 0;
    pm_munmap(pm.acc, PM_ACC); pm.acc = 0; pm_munmap(pm.wtc, PM_WTC); pm.wtc = 0;
}
/* N.n */
static void pm_begin(int n, int k10) {
    pm_free(); pm.armed = 1; pm.state = 0; pm.nreg = 0; pm.ncopied = 0; pm.nmerged = 0; pm.job = 0; pm_nx = 0;
    mg.K10 = k10 < 5 ? 25 : k10; mg.total = 0;
}
/* N.p(buffer, rowStride): one raw 50 MP frame of the shot (from the props slots) */
static int pm_register(u16* p, int rs) {
    if (!pm.armed || pm.state != 0 || !p) return -1;
    for (int i = 0; i < pm.nreg; ++i) if (pm.reg[i] == p) return pm.nreg;
    if (pm.nreg >= MG_MAXF) {                              /* P284: frames past MG_MAXF get the merged copy too */
        for (int j = 0; j < pm_nx; ++j) if (pm_xreg[j] == p) return pm.nreg;
        if (pm_nx < PM_MAXX) pm_xreg[pm_nx++] = p;
        return pm.nreg;
    }
    pm.reg[pm.nreg] = p; pm.regrs[pm.nreg] = rs; pm.used[pm.nreg] = 0; ++pm.nreg;
    return pm.nreg;
}
static int pm_find(const u16* p) { for (int i = 0; i < pm.nreg; ++i) if (pm.reg[i] == p) return i; return -1; }
static void pm_add(int kind, int frame, int n) {
    if (pm.nph >= PM_MAXPH || n <= 0) return;
    pm.ph_kind[pm.nph] = kind; pm.ph_frame[pm.nph] = frame; pm.ph_n[pm.nph] = n; pm.ph_start[pm.nph] = pm.total;
    pm.done[pm.nph] = 0; pm.total += n; ++pm.nph;
}
static void pm_add_remosaic(int frame) {
    int nb = pm.nb;
    pm_add(P_SETUP, frame, 1);
    if (((pm.wbits >> 18) & 1) && pm.mode != 2) pm_add(P_QSC, frame, nb);
    if (pm.mode == 2) pm_add(P_XC, frame, nb);                     /* P297: already Bayer: copy */
    else { pm_add(P_A, frame, nb); pm_add(P_M, frame, nb); pm_add(P_C, frame, nb); }
    if (qj.dnc > 0 || qj.dnl > 0) { pm_add(P_D1, frame, nb); pm_add(P_D2, frame, nb); pm_add(P_D3, frame, nb); pm_add(P_D4, frame, nb); }
    pm_add(P_NZ, frame, 1);
}
/* P271: 50 -> 25 MP (test, Motion button). The merged Bayer frame is resampled by 1/sqrt(2) per axis, each colour plane
   on its own (sample centres mapped through the scale, so R, G and B stay registered), separable Catmull-Rom stretched
   by 1/scale (anti-aliasing), in place in pm.keep: rows first, then 16-column blocks; then copied to the frame. */
#define DS_NT 6
static int ds_w2, ds_h2, ds_x0[8192], ds_y0[8192]; static float ds_wx[8192][DS_NT], ds_wy[8192][DS_NT];
static float ds_cr(float t) { t = t < 0 ? -t : t; if (t < 1) return 1.5f * t * t * t - 2.5f * t * t + 1; if (t < 2) return -0.5f * t * t * t + 2.5f * t * t - 4 * t + 2; return 0; }
#ifndef DS_W2
#define DS_W2 5792                                        /* P271B: fixed 25 MP frame = GCam's StaticMetadata size */
#define DS_H2 4344
#endif
/* P282: 25 MP = demosaic -> RGB Lanczos-3 downscale -> remosaic (the ISP-style raw rescaler: resample the full colour
   image, then rebuild the Bayer pattern), instead of resampling each colour plane on its own. Per band of 32 output
   rows: the source rows it needs are demosaiced (gradient-directed green, colour-difference R/B), resampled
   horizontally, then vertically, and the RGGB sample of each output site is written to mg.buf[0]; P_DSV copies the
   result back to pm.keep (later frames of the shot copy pm.keep). Reads pm.keep only. */
#define DZ_R 3.f                                           /* Lanczos lobes */
#define DZ_NT 10
#define DZ_NRM 64
#define DZ_SLOTS 16
#define DZ_SLOT ((i64)6 * 8192 + (i64)DZ_NRM * 5792 * 3)
static volatile int dz_lock[DZ_SLOTS];
static int dz_x0[8192], dz_y0[8192]; static float dz_wx[8192][DZ_NT], dz_wy[8192][DZ_NT];
static float dz_sin(float x) {                             /* no libm in libtbin: |x| <= 3 pi here */
    const float PI = 3.14159265f; while (x > PI) x -= 2.f * PI; while (x < -PI) x += 2.f * PI;
    if (x > 0.5f * PI) x = PI - x; else if (x < -0.5f * PI) x = -PI - x;
    float x2 = x * x; return x * (1.f - x2 / 6.f * (1.f - x2 / 20.f * (1.f - x2 / 42.f * (1.f - x2 / 72.f * (1.f - x2 / 110.f)))));
}
static float dz_lz(float x) {
    x = x < 0 ? -x : x; if (x >= DZ_R) return 0.f; if (x < 1e-6f) return 1.f;
    float a = 3.14159265f * x, b = a / DZ_R; return (dz_sin(a) / a) * (dz_sin(b) / b);
}
static void dz_taps(int n2, int n, int* first, float (*wt)[DZ_NT]) {
    const float s = (float)n2 / (float)n;
    for (int o = 0; o < n2; ++o) {
        float c = ((float)o + 0.5f) / s - 0.5f;
        float f0 = c - DZ_R / s; int k0 = (int)f0; if ((float)k0 > f0) --k0; ++k0; float sum = 0, w[DZ_NT];
        for (int t = 0; t < DZ_NT; ++t) { w[t] = dz_lz(((float)(k0 + t) - c) * s); sum += w[t]; }
        for (int t = 0; t < DZ_NT; ++t) wt[o][t] = w[t] / sum;
        first[o] = k0;
    }
}
static void ds_init(void) {
    ds_w2 = DS_W2; ds_h2 = DS_H2;
    dz_taps(ds_w2, pm.w, dz_x0, dz_wx); dz_taps(ds_h2, pm.h, dz_y0, dz_wy);
}
static inline int dz_cl(int v, int n) { return v < 0 ? 0 : (v > n - 1 ? n - 1 : v); }
static inline int dz_par(int v, int n, int par) {          /* clamp keeping the CFA parity of v */
    if (v < 0) v = par; else if (v > n - 1) v = ((n - 1) & 1) == par ? n - 1 : n - 2; return v;
}
#define DZ_RAW(x, y) ((float)pm.keep[(i64)(y) * OW + (x)] - 64.f)
static void dz_green_row(int y, float* G) {                /* full-width green of source row y */
    int w = pm.w, h = pm.h;
    for (int x = 0; x < w; ++x) {
        if (qch(x & 1, y & 1) == 1) { G[x] = DZ_RAW(x, y); continue; }
        int xl = dz_par(x - 1, w, (x - 1) & 1), xr = dz_par(x + 1, w, (x + 1) & 1);
        int xl2 = dz_par(x - 2, w, x & 1), xr2 = dz_par(x + 2, w, x & 1);
        int yu = dz_par(y - 1, h, (y - 1) & 1), yd = dz_par(y + 1, h, (y + 1) & 1);
        int yu2 = dz_par(y - 2, h, y & 1), yd2 = dz_par(y + 2, h, y & 1);
        float c = DZ_RAW(x, y);
        float gl = DZ_RAW(xl, y), gr = DZ_RAW(xr, y), gu = DZ_RAW(x, yu), gd = DZ_RAW(x, yd);
        float lh = 2.f * c - DZ_RAW(xl2, y) - DZ_RAW(xr2, y), lv = 2.f * c - DZ_RAW(x, yu2) - DZ_RAW(x, yd2);
        float eh = 0.5f * (gl + gr) + 0.25f * lh, ev = 0.5f * (gu + gd) + 0.25f * lv;
        float dh = __builtin_fabsf(gl - gr) + __builtin_fabsf(lh) + 1.f, dv = __builtin_fabsf(gu - gd) + __builtin_fabsf(lv) + 1.f;
        float wh = 1.f / (dh * dh), wv = 1.f / (dv * dv);
        float g = (eh * wh + ev * wv) / (wh + wv);
        float lo = gl < gr ? gl : gr, hi = gl < gr ? gr : gl;          /* keep inside the 4 neighbours */
        if (gu < lo) lo = gu; if (gd < lo) lo = gd; if (gu > hi) hi = gu; if (gd > hi) hi = gd;
        G[x] = g < lo ? lo : (g > hi ? hi : g);
    }
}
static void ds_rows(int i) {
    int w = pm.w, h = pm.h, w2 = ds_w2, oa = i * 32, ob = oa + 32 > ds_h2 ? ds_h2 : oa + 32;
    if (oa >= ds_h2) { for (int y = oa; y < OH && y < oa + 32; ++y) { u16* d = mg.buf[0] + (i64)y * OW; for (int x = 0; x < OW; ++x) d[x] = 64; } return; }
    int ys = dz_y0[oa], ye = dz_y0[ob - 1] + DZ_NT - 1, nr = ye - ys + 1;
    if (nr > DZ_NRM) nr = DZ_NRM;
    int slot = 0;                                          /* scratch slot in pm.acc (free after FIN) */
    for (;;) { if (!__atomic_exchange_n(&dz_lock[slot], 1, __ATOMIC_ACQUIRE)) break; slot = (slot + 1) % DZ_SLOTS; }
    float* base = pm.acc + (i64)slot * DZ_SLOT;
    float* G3 = base;                                      /* green ring: rows y-1, y, y+1 */
    float* RGB = base + 3 * 8192;                          /* one demosaiced source row */
    float* Hb = base + 6 * 8192;                           /* horizontally resampled rows */
    float* Gm = G3; float* G0 = G3 + w; float* Gp = G3 + 2 * w; int gy = -100000;
    for (int r = 0; r < nr; ++r) {
        int y = dz_cl(ys + r, h);
        if (gy != y) {                                     /* green of y-1, y, y+1 (parity-clamped) */
            dz_green_row(dz_par(y - 1, h, (y - 1) & 1), Gm); dz_green_row(y, G0); dz_green_row(dz_par(y + 1, h, (y + 1) & 1), Gp); gy = y;
        }
        for (int x = 0; x < w; ++x) {
            int c = qch(x & 1, y & 1); float g = G0[x], v = DZ_RAW(x, y), R, B;
            int xl = dz_cl(x - 1, w), xr = dz_cl(x + 1, w);
            if (c == 1) {                                  /* green site: R/B from the row or the column */
                float dh = 0.5f * ((DZ_RAW(xl, y) - G0[xl]) + (DZ_RAW(xr, y) - G0[xr]));
                float dv = 0.5f * ((DZ_RAW(x, dz_par(y - 1, h, (y - 1) & 1)) - Gm[x]) + (DZ_RAW(x, dz_par(y + 1, h, (y + 1) & 1)) - Gp[x]));
                if (qch((x + 1) & 1, y & 1) == 0) { R = g + dh; B = g + dv; } else { B = g + dh; R = g + dv; }
            } else {                                       /* R or B site: the other one from the 4 diagonals */
                int yu = dz_par(y - 1, h, (y - 1) & 1), yd = dz_par(y + 1, h, (y + 1) & 1);
                float dd = 0.25f * ((DZ_RAW(xl, yu) - Gm[xl]) + (DZ_RAW(xr, yu) - Gm[xr]) + (DZ_RAW(xl, yd) - Gp[xl]) + (DZ_RAW(xr, yd) - Gp[xr]));
                if (c == 0) { R = v; B = g + dd; } else { B = v; R = g + dd; }
            }
            RGB[3 * x] = R; RGB[3 * x + 1] = g; RGB[3 * x + 2] = B;
        }
        float* H = Hb + (i64)r * w2 * 3;
        for (int o = 0; o < w2; ++o) {
            float a0 = 0, a1 = 0, a2 = 0; int k0 = dz_x0[o];
            for (int t = 0; t < DZ_NT; ++t) { const float* q = RGB + 3 * dz_cl(k0 + t, w); float wk = dz_wx[o][t]; a0 += wk * q[0]; a1 += wk * q[1]; a2 += wk * q[2]; }
            H[3 * o] = a0; H[3 * o + 1] = a1; H[3 * o + 2] = a2;
        }
        /* next row needs the green ring shifted by one */
        if (r + 1 < nr && dz_cl(ys + r + 1, h) == y + 1 && y + 2 < h) {
            float* t = Gm; Gm = G0; G0 = Gp; Gp = t; dz_green_row(dz_par(y + 2, h, y & 1), Gp); gy = y + 1;
        }
    }
    for (int oy = oa; oy < ob; ++oy) {
        u16* d = mg.buf[0] + (i64)oy * OW; int k0 = dz_y0[oy];
        for (int o = 0; o < w2; ++o) {
            int c = qch(o & 1, oy & 1); float a = 0;
            for (int t = 0; t < DZ_NT; ++t) { int rr = dz_cl(k0 + t, h) - ys; rr = rr < 0 ? 0 : (rr > nr - 1 ? nr - 1 : rr); a += dz_wy[oy][t] * Hb[((i64)rr * w2 + o) * 3 + c]; }
            int q = (int)(a + 64.5f); d[o] = (u16)(q < 0 ? 0 : (q > 1023 ? 1023 : q));
        }
        for (int x = w2; x < OW; ++x) d[x] = 64;
    }
    if (ob == ds_h2) for (int y = ds_h2; y < OH && y < oa + 32; ++y) { u16* d = mg.buf[0] + (i64)y * OW; for (int x = 0; x < OW; ++x) d[x] = 64; }
    __atomic_store_n(&dz_lock[slot], 0, __ATOMIC_RELEASE);
}
static void ds_cols(int i) {                               /* P282: result back to pm.keep */
    int a = i * 32, b = a + 32 > OH ? OH : a + 32;
    for (int y = a; y < b; ++y) { const u16* s2 = mg.buf[0] + (i64)y * OW; u16* d = pm.keep + (i64)y * OW; for (int x = 0; x < OW; ++x) d[x] = s2[x]; }
}
/* from quad_start after a successful quad_prepare of this frame (src, dst, w bits) -> 1 = pre-merge or copy job set */
static int pm_start(const u16* src, u16* dst, int wbits) {
    pm.job = 0;
    if (!pm.armed || qj.mode == 1) return 0;
    int i = pm_find(src);
    if (i < 0) {                                           /* P284: a frame past MG_MAXF: same merged copy (25 MP: same size) */
        int x = -1; for (int j = 0; j < pm_nx; ++j) if (pm_xreg[j] == src) x = j;
        if (x < 0 || pm.state != 2 || !pm.keep) return 0;
        pm_xreg[x] = 0; pm.nph = 0; pm.total = 0; pm.next = 0;
        mg.buf[0] = dst; pm_add(P_COPY, 0, (OH + 31) / 32); pm.job = 2; return 1;
    }
    if (pm.state == 2) {                                   /* later frame: the merged copy */
        if (!pm.keep) return 0;
        pm.used[i] = 1; pm.nph = 0; pm.total = 0; pm.next = 0;
        mg.buf[0] = dst; pm_add(P_COPY, 0, (OH + 31) / 32); pm.job = 2; return 1;
    }
    if (pm.state != 0 || pm.nreg < 2) return 0;
    for (int k = 0; k < pm.nreg; ++k) if (k != i && !pm.regrs[k]) return 0;
    pm.tmp = (u16*)q_acquire(); pm.keep = pm.tmp;          /* P253: the result reuses the frame buffer (-100 MB) */
    if (!pm.acc) pm.acc = (float*)q_mmap(PM_ACC);
    if (!pm.wtc) pm.wtc = (float*)q_mmap(PM_WTC);
    if (!mg_L1) mg_L1 = (u16*)q_mmap((i64)MG_MAXF * 1024 * 768 * 2);
    if (!mg_L0) mg_L0 = (u16*)q_mmap((i64)4096 * 3072 * 2);
    if (!pm.tmp || !pm.keep || !pm.acc || !pm.wtc || !mg_L1 || !mg_L0) { pm_free(); mg_say("premerge off: no memory"); pm.armed = 0; return 0; }
    mg_crinit(); mg_kinit();
    pm.ref = i; pm.used[i] = 1; pm.state = 1; pm.wbits = wbits; pm.w = qj.w; pm.h = qj.h; pm.mode = qj.mode;
    pm.nb = qj.nbands; pm.skip = 0; pm.nmerged = 1;
    mg.w = qj.w; mg.h = qj.h; mg.n = 2; mg.buf[0] = dst; mg.buf[1] = pm.tmp;
    mg.w1 = mg.w / 8; mg.h1 = mg.h / 8; mg.w0 = mg.w / 2; mg.h0 = mg.h / 2;
    mg.tx = (mg.w + MG_T - 1) / MG_T; mg.ty = (mg.h + MG_T - 1) / MG_T;
    for (int t = 0; t < MG_TY; ++t) { mg.wsum[t] = 0; mg.wcnt[t] = 0; mg.rej[t] = 0; }
    if (nzfit) { mg.va = (float)(nzS * 959.0); mg.vb = (float)(nzO * 959.0 * 959.0); } else { mg.va = 0.6f; mg.vb = 1.0f; }
    pm.nph = 0; pm.total = 0; pm.next = 0;
    /* P248: sharpness of every raw frame first, the sharpest becomes the reference (slot 0, remosaiced into this
       frame's buffer), frames clearly softer than it are left out; slots = merge order */
    pm_add(P_SHARP, 0, pm.nreg * 16); pm_add(P_PICK, 0, 1);
    pm_add_remosaic(0);
    pm_add(P_L0, 0, mg.h1); pm_add(P_INIT, 0, mg.ty);
    for (int j = 1; j < pm.nreg; ++j) {
        pm_add_remosaic(j);
        pm_add(P_L, j, mg.h1); pm_add(P_G, j, 1); pm_add(P_TA, j, mg.ty); pm_add(P_MED, j, 1);
        pm_add(P_TA2, j, mg.ty); if (MG_AFFINE) pm_add(P_FIT, j, 1); pm_add(P_ACC, j, mg.ty);
    }
    pm_add(P_FIN, 0, mg.ty);
    if (pm_ds) { ds_init(); pm_add(P_DSH, 0, (OH + 31) / 32); pm_add(P_DSV, 0, (OH + 31) / 32); }   /* P282 */
    pm.fitn = pm.fitres = pm.nfit = pm.refx = pm.refy = pm.lockeep = 0; pm.lowdn = 0; pm.trej = 0;
    pm.job = 1; pm.t0 = 0; pm.cur = -1;
    __atomic_store_n(&nz_have_reset, 1, __ATOMIC_SEQ_CST);
    return 1;
}
/* rows L1 of frame slot 1 (k=1 only) or L1 + L0 of the reference (slot 0) */
static void pm_rowL(int r, int slot) {
    int cs[8192]; int w = mg.w, w1 = mg.w1;
    const u16* b = mg.buf[slot] + (i64)(8 * r) * OW;
    for (int x = 0; x < w; ++x) cs[x] = 0;
    for (int j = 0; j < 8; ++j) { const u16* s = b + (i64)j * OW; for (int x = 0; x < w; ++x) cs[x] += s[x]; }
    u16* o = mg_L1 + (i64)slot * 1024 * 768 + (i64)r * w1;
    for (int c = 0; c < w1; ++c) { int s = 0; for (int i = 0; i < 8; ++i) s += cs[8 * c + i]; o[c] = (u16)(s >> 4); }
    if (slot) return;
    for (int j = 0; j < 4; ++j) {
        int y = 4 * r + j; const u16* s0 = mg.buf[0] + (i64)(2 * y) * OW; const u16* s1 = s0 + OW;
        u16* oo = mg_L0 + (i64)y * mg.w0;
        for (int x = 0; x < mg.w0; ++x) oo[x] = (u16)(s0[2 * x] + s0[2 * x + 1] + s1[2 * x] + s1[2 * x + 1]);
    }
}
static void pm_init(int ty) {                               /* acc = reference, cell weights 1 */
    int y0 = ty * MG_T, y1 = y0 + MG_T > mg.h ? mg.h : y0 + MG_T;
    for (int y = y0; y < y1; ++y) { const u16* s = mg.buf[0] + (i64)y * OW; float* a = pm.acc + (i64)y * OW; for (int x = 0; x < mg.w; ++x) a[x] = s[x]; }
    if (MG_KR) { for (int y = y0; y < y1; ++y) { float* q = pm.wtc + (i64)y * OW; for (int x = 0; x < mg.w; ++x) q[x] = 1.f; } }
    else for (int y = y0 / 2; y < y1 / 2; ++y) { float* q = pm.wtc + (i64)y * mg.w0; for (int x = 0; x < mg.w0; ++x) q[x] = 1.f; }
}
/* frame slot 1 (aligned by its tile shifts) added to the running sum, weights vs the reference */
/* P267: the tile's resampled frame F (MG_PW x MG_PW around (X0-2, Y0-2)) at a constant quarter-px shift, separable:
   every needed source row is filtered horizontally once (4 taps), then each output pixel vertically (4 taps), instead
   of 16 taps per pixel in mg_smp. Same taps, weights and summation order as mg_smp -> bit-identical output. */
#define MG_HR 96
static void mg_tile_smp(const u16* B, int X0, int Y0, int sxq, int syq, float* F) {
    int w = mg.w, h = mg.h;
    static const float one[4] = {0, 1, 0, 0};
    int xs[MG_PW][4], ys[MG_PW][4], nx, ny; const float* wx; const float* wy;
    int fu = sxq & 7, fv = syq & 7;
    nx = fu ? 4 : 1; wx = fu ? mg_cr[fu] : one + 1; ny = fv ? 4 : 1; wy = fv ? mg_cr[fv] : one + 1;
    for (int i = 0; i < MG_PW; ++i) {
        int px = i & 1, X = mg_cl(X0 - 2 + i, px, w - 2 + px), iu = (4 * (X - px) + sxq) >> 3;
        if (!fu) xs[i][0] = mg_cl(2 * iu + px, px, w - 2 + px);
        else for (int k = 0; k < 4; ++k) xs[i][k] = mg_cl(2 * (iu - 1 + k) + px, px, w - 2 + px);
    }
    int rmin = 1 << 30, rmax = -1;
    for (int j = 0; j < MG_PW; ++j) {
        int py = j & 1, Y = mg_cl(Y0 - 2 + j, py, h - 2 + py), iv = (4 * (Y - py) + syq) >> 3;
        if (!fv) ys[j][0] = mg_cl(2 * iv + py, py, h - 2 + py);
        else for (int k = 0; k < 4; ++k) ys[j][k] = mg_cl(2 * (iv - 1 + k) + py, py, h - 2 + py);
        for (int k = 0; k < ny; ++k) { if (ys[j][k] < rmin) rmin = ys[j][k]; if (ys[j][k] > rmax) rmax = ys[j][k]; }
    }
    if (rmax - rmin + 1 > MG_HR) {                         /* cannot happen for MG_T 64; keep the exact fallback */
        for (int j = 0; j < MG_PW; ++j) for (int i = 0; i < MG_PW; ++i) {
            int X = mg_cl(X0 - 2 + i, (i & 1), w - 2 + (i & 1)), Y = mg_cl(Y0 - 2 + j, (j & 1), h - 2 + (j & 1));
            F[j * MG_PW + i] = mg_smp(B, X, Y, sxq, syq);
        }
        return;
    }
    float H[MG_HR * MG_PW];
    for (int r = rmin; r <= rmax; ++r) {
        const u16* row = B + (i64)r * OW; float* o = H + (r - rmin) * MG_PW;
        if (nx == 1) for (int i = 0; i < MG_PW; ++i) { float a = 0; a += wx[0] * (float)row[xs[i][0]]; o[i] = a; }
        else for (int i = 0; i < MG_PW; ++i) {
            const int* x = xs[i]; float a = 0;
            a += wx[0] * (float)row[x[0]]; a += wx[1] * (float)row[x[1]]; a += wx[2] * (float)row[x[2]]; a += wx[3] * (float)row[x[3]];
            o[i] = a;
        }
    }
    for (int j = 0; j < MG_PW; ++j) {
        float* o = F + j * MG_PW;
        if (ny == 1) { const float* h0 = H + (ys[j][0] - rmin) * MG_PW; for (int i = 0; i < MG_PW; ++i) { float v = 0; v += wy[0] * h0[i]; o[i] = v; } }
        else {
            const float* h0 = H + (ys[j][0] - rmin) * MG_PW; const float* h1 = H + (ys[j][1] - rmin) * MG_PW;
            const float* h2 = H + (ys[j][2] - rmin) * MG_PW; const float* h3 = H + (ys[j][3] - rmin) * MG_PW;
            for (int i = 0; i < MG_PW; ++i) { float v = 0; v += wy[0] * h0[i]; v += wy[1] * h1[i]; v += wy[2] * h2[i]; v += wy[3] * h3[i]; o[i] = v; }
        }
    }
}
/* P288: frequency-domain robust merge (idea: Google HDR+, Hasinoff et al. 2016; own implementation). Per tile and Bayer
   plane, 16x16-sample blocks with 50 % overlap (sin^2 window, sums to 1): D = R - F in the 2-D DFT, the frame keeps
   only the frequencies where D is explained by noise: C = F + A (R - F), A = |D|^2 / (|D|^2 + c sigma_D^2). The result
   goes into the same running sum (weight 1 per frame and cell); the tile-level rejection above stays. */
#ifndef MG_FQ
#define MG_FQ 1
#endif
#ifndef MG_FQW
#define MG_FQW 1                                           /* P334 cell motion weights on the frequency merge (P335 off: over-rejected foliage; P349 on, K x 2.0, window test off) */
#endif
#ifndef MG_FQK
#define MG_FQK 2.0f                                        /* P334: their threshold, x the spatial merge's K */
#endif
#ifndef MG_FQB
#define MG_FQB 0.f                                         /* P334: 7x7-cell window motion test threshold (z^2); 0 = off (P349) */
#endif
#ifndef FQ_SKIP
#define FQ_SKIP 0
#endif
#ifndef MG_FQC
#define MG_FQC 16.0f                                       /* P349: 64 -> 16, the frame keeps a bin only within ~4 sigma (was ~8) */
#endif
#ifndef FQ_N
#define FQ_N 16
#endif
#define FQ_B (FQ_N / 2)                                    /* border, plane samples */
#define FQ_NB (64 / FQ_N + 1)                              /* blocks per axis and tile */
#define FQ_NN (FQ_N * FQ_N)
#define FQ_P (32 + 2 * FQ_B)
static float fq_cs[FQ_N], fq_sn[FQ_N], fq_w[FQ_N]; static volatile int fq_ok;
static void fq_init(void) {
    if (fq_ok) return;
    for (int i = 0; i < FQ_N; ++i) {
        float a = 6.28318531f * (float)i / FQ_N; if (a > 3.14159265f) a -= 6.28318531f;
        float c = a + 1.57079633f; if (c > 3.14159265f) c -= 6.28318531f;
        fq_sn[i] = dz_sin(a); fq_cs[i] = dz_sin(c);
        float h = dz_sin(3.14159265f * ((float)i + 0.5f) / FQ_N); fq_w[i] = h * h;
    }
    fq_ok = 1;
}
static void fq_1d(float* re, float* im, int st, int inv) {
    int j = 0;
    for (int i = 0; i < FQ_N - 1; ++i) {
        if (i < j) { float t = re[i * st]; re[i * st] = re[j * st]; re[j * st] = t; t = im[i * st]; im[i * st] = im[j * st]; im[j * st] = t; }
        int k = FQ_N >> 1; while (k <= j) { j -= k; k >>= 1; } j += k;
    }
    for (int len = 2; len <= FQ_N; len <<= 1) {
        int h = len >> 1, step = FQ_N / len;
        for (int i = 0; i < FQ_N; i += len) for (int k = 0; k < h; ++k) {
            float wr = fq_cs[k * step], wi = inv ? fq_sn[k * step] : -fq_sn[k * step];
            int a = (i + k) * st, b = (i + k + h) * st;
            float xr = re[b] * wr - im[b] * wi, xi = re[b] * wi + im[b] * wr;
            re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
        }
    }
}
/* 2-D FFT: column pass on whole rows (16 floats at a time, vectorises), transpose, column pass. The forward result is
   transposed ([kx][ky]); the inverse of such a spectrum comes back in the original orientation. */
static void fq_cols(float* re, float* im, int inv) {
    for (int i = 0; i < FQ_N; ++i) { int j = 0; for (int b = 1, r = FQ_N >> 1; b < FQ_N; b <<= 1, r >>= 1) if (i & b) j |= r;
        if (i < j) for (int c = 0; c < FQ_N; ++c) {
        float t = re[i * FQ_N + c]; re[i * FQ_N + c] = re[j * FQ_N + c]; re[j * FQ_N + c] = t;
        t = im[i * FQ_N + c]; im[i * FQ_N + c] = im[j * FQ_N + c]; im[j * FQ_N + c] = t; } }
    for (int len = 2; len <= FQ_N; len <<= 1) {
        int h = len >> 1, step = FQ_N / len;
        for (int i = 0; i < FQ_N; i += len) for (int k = 0; k < h; ++k) {
            float wr = fq_cs[k * step], wi = inv ? fq_sn[k * step] : -fq_sn[k * step];
            float* ar = re + (i + k) * FQ_N; float* ai = im + (i + k) * FQ_N; float* br = re + (i + k + h) * FQ_N; float* bi = im + (i + k + h) * FQ_N;
            for (int c = 0; c < FQ_N; ++c) {
                float xr = br[c] * wr - bi[c] * wi, xi = br[c] * wi + bi[c] * wr;
                br[c] = ar[c] - xr; bi[c] = ai[c] - xi; ar[c] += xr; ai[c] += xi;
            }
        }
    }
}
static void fq_tr(float* a) { for (int j = 0; j < FQ_N; ++j) for (int i = j + 1; i < FQ_N; ++i) { float t = a[j * FQ_N + i]; a[j * FQ_N + i] = a[i * FQ_N + j]; a[i * FQ_N + j] = t; } }
static void fq_2d(float* re, float* im, int inv) { fq_cols(re, im, inv); fq_tr(re); fq_tr(im); fq_cols(re, im, inv); }
/* forward FFT of two real windowed blocks at once (Z = R + iF), split by symmetry */
static void fq_plane(const float* R, const float* F, float* out) {
    float zr[FQ_NB * FQ_NB][FQ_NN], zi[FQ_NB * FQ_NB][FQ_NN]; float sD[FQ_NB * FQ_NB];
    for (int i = 0; i < 32 * 32; ++i) out[i] = 0;
    int nb = 0;
    for (int by = -FQ_B; by < 32; by += FQ_N / 2) for (int bx = -FQ_B; bx < 32; bx += FQ_N / 2, ++nb) {
        float m = 0, *re = zr[nb], *im = zi[nb];
        for (int j = 0; j < FQ_N; ++j) {
            const float* r = R + (by + FQ_B + j) * FQ_P + bx + FQ_B; const float* f = F + (by + FQ_B + j) * FQ_P + bx + FQ_B;
            for (int i = 0; i < FQ_N; ++i) { float w = fq_w[j] * fq_w[i]; re[j * FQ_N + i] = w * r[i]; im[j * FQ_N + i] = w * f[i]; m += r[i]; }
        }
        m *= 1.f / FQ_NN; float sg = m > 64.f ? m - 64.f : 0.f;
        sD[nb] = MG_FQC * 2.f * (mg.va * sg + mg.vb + (MG_REL * sg) * (MG_REL * sg)) * (0.140625f * FQ_NN);   /* sum w^2 = (3N/8)^2 */
        fq_2d(re, im, 0);
        float sd = sD[nb];
        for (int ky = 0; ky < FQ_N; ++ky) for (int kx = 0; kx < FQ_N; ++kx) {      /* pairs k, -k in place */
            int k = ky * FQ_N + kx, q = ((FQ_N - ky) & (FQ_N - 1)) * FQ_N + ((FQ_N - kx) & (FQ_N - 1));
            if (q < k) continue;
            float Rr = 0.5f * (re[k] + re[q]), Ri = 0.5f * (im[k] - im[q]);      /* R_k = (Z_k + conj Z_-k) / 2 */
            float Fr = 0.5f * (im[k] + im[q]), Fi = -0.5f * (re[k] - re[q]);     /* F_k = (Z_k - conj Z_-k) / 2i */
            float dr = Rr - Fr, di = Ri - Fi, d2 = dr * dr + di * di, A = d2 / (d2 + sd);
            float cr = Fr + A * dr, ci = Fi + A * di;
            re[k] = cr; im[k] = ci; re[q] = cr; im[q] = -ci;                          /* C_-k = conj C_k */
        }
    }
    /* inverse: the results are real (Hermitian spectra) -> two blocks per inverse FFT (C1 + i C2) */
    for (int b0 = 0; b0 < FQ_NB * FQ_NB; b0 += 2) {
        int b1 = b0 + 1 < FQ_NB * FQ_NB ? b0 + 1 : -1;
        float re[FQ_NN], im[FQ_NN];
        for (int k = 0; k < FQ_NN; ++k) {
            if (b1 >= 0) { re[k] = zr[b0][k] - zi[b1][k]; im[k] = zi[b0][k] + zr[b1][k]; }
            else { re[k] = zr[b0][k]; im[k] = zi[b0][k]; }
        }
        fq_2d(re, im, 1);
        for (int t = 0; t < 2; ++t) {
            int bb = t ? b1 : b0; if (bb < 0) break;
            const float* v = t ? im : re; int by = -FQ_B + (bb / FQ_NB) * (FQ_N / 2), bx = -FQ_B + (bb % FQ_NB) * (FQ_N / 2);
            for (int j = 0; j < FQ_N; ++j) { int y = by + j; if (y < 0 || y >= 32) continue;
                for (int i = 0; i < FQ_N; ++i) { int x = bx + i; if (x < 0 || x >= 32) continue; out[y * 32 + x] += v[j * FQ_N + i] * (1.f / FQ_NN); } }
        }
    }
}
static void fq_tile(int X0, int Y0, int tw, int th, int sx, int sy, const float* WS) {
    int w0 = mg.w0, h0 = mg.h0; const u16* B = mg.buf[1]; const u16* R0 = mg.buf[0];
    float R[FQ_P * FQ_P], F[FQ_P * FQ_P], O[32 * 32], H[(FQ_P + 3) * FQ_P];
    fq_init();
    const float* wx = mg_cr[sx & 7]; const float* wy = mg_cr[sy & 7];
    int ox = (sx >> 3) - 1, oy = (sy >> 3) - 1;                 /* plane offsets of the first tap */
    for (int p = 0; p < 4; ++p) {
        int py = p >> 1, px = p & 1, c0 = X0 / 2 - FQ_B, r0 = Y0 / 2 - FQ_B;
        for (int j = 0; j < FQ_P; ++j) { const u16* row = R0 + (i64)(2 * mg_cl(r0 + j, 0, h0 - 1) + py) * OW + px;
            for (int i = 0; i < FQ_P; ++i) R[j * FQ_P + i] = (float)row[2 * mg_cl(c0 + i, 0, w0 - 1)]; }
        for (int j = 0; j < FQ_P + 3; ++j) {                    /* horizontal taps, plane rows r0 + oy + j */
            const u16* row = B + (i64)(2 * mg_cl(r0 + oy + j, 0, h0 - 1) + py) * OW + px; float* o = H + j * FQ_P;
            for (int i = 0; i < FQ_P; ++i) { int c = c0 + ox + i;
                o[i] = wx[0] * (float)row[2 * mg_cl(c, 0, w0 - 1)] + wx[1] * (float)row[2 * mg_cl(c + 1, 0, w0 - 1)]
                     + wx[2] * (float)row[2 * mg_cl(c + 2, 0, w0 - 1)] + wx[3] * (float)row[2 * mg_cl(c + 3, 0, w0 - 1)]; }
        }
        for (int j = 0; j < FQ_P; ++j) { const float* h = H + j * FQ_P;
            for (int i = 0; i < FQ_P; ++i) F[j * FQ_P + i] = wy[0] * h[i] + wy[1] * h[FQ_P + i] + wy[2] * h[2 * FQ_P + i] + wy[3] * h[3 * FQ_P + i]; }
        if (FQ_SKIP) { for (int j = 0; j < 32; ++j) for (int i = 0; i < 32; ++i) O[j * 32 + i] = F[(j + FQ_B) * FQ_P + i + FQ_B]; } else fq_plane(R, F, O);
        for (int j = 0; j < th / 2; ++j) for (int i = 0; i < tw / 2; ++i) {
            float wk = WS ? WS[j * 32 + i] : 1.f; if (wk <= 0.005f) continue;
            pm.acc[(i64)(Y0 + 2 * j + py) * OW + X0 + 2 * i + px] += wk * O[j * 32 + i];
        }
    }
    for (int j = 0; j < th / 2; ++j) for (int i = 0; i < tw / 2; ++i) {
        float wk = WS ? WS[j * 32 + i] : 1.f; if (wk <= 0.005f) continue;
        pm.wtc[(i64)(Y0 / 2 + j) * mg.w0 + X0 / 2 + i] += wk;
    }
}
static void pm_acc(int ty) {
    int w = mg.w, h = mg.h, w0 = mg.w0, h0 = mg.h0;
    float F[MG_PW * MG_PW]; float Pk[34 * 34]; int Pr[34 * 34]; float WK[32 * 32], WS[32 * 32];
    float K2 = (float)mg.K10 * (float)mg.K10 / 100.f;
    int nrej = 0;
    for (int tx = 0; tx < mg.tx; ++tx) {
        int t = ty * MG_TX + tx, X0 = tx * MG_T, Y0 = ty * MG_T;
        int tw = X0 + MG_T <= w ? MG_T : w - X0, th = Y0 + MG_T <= h ? MG_T : h - Y0;
        int c0 = X0 / 2, r0 = Y0 / 2, cw = tw / 2, ch = th / 2;
        for (int j = 0; j < 34; ++j) for (int i = 0; i < 34; ++i)
            Pr[j * 34 + i] = mg_L0[(i64)mg_cl(r0 - 1 + j, 0, h0 - 1) * w0 + mg_cl(c0 - 1 + i, 0, w0 - 1)];
        int sx = mg_sh[1][0][t], sy = mg_sh[1][1][t];
        const u16* B = mg.buf[1];
        mg_tile_smp(B, X0, Y0, sx, sy, F);
        for (int j = 0; j < 34; ++j) for (int i = 0; i < 34; ++i) {
            const float* f = F + (2 * j) * MG_PW + 2 * i; Pk[j * 34 + i] = f[0] + f[1] + f[MG_PW] + f[MG_PW + 1];
        }
        /* P258: tile-level mismatch. At high ISO a moving face differs from the reference by less than K sigma in each
           cell, so every cell was accepted and the misaligned detail was averaged into a smeared, painterly patch.
           Over the whole tile those small differences add up: mean (cell difference / expected noise)^2 is ~1 for an
           aligned tile; above MG_TREJ the frame is left out of this tile (its pixels keep the reference). */
        {
            double zs = 0; int zn = 0;
            for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) {
                float v = (float)Pr[(cy + 1) * 34 + cx + 1] * 0.25f, sg = v > 64.f ? v - 64.f : 0.f;
                float var = mg.va * sg + mg.vb + (MG_REL * sg) * (MG_REL * sg);
                float d1 = Pk[(cy + 1) * 34 + cx + 1] - (float)Pr[(cy + 1) * 34 + cx + 1];
                zs += d1 * d1 / (16.f * var); ++zn;
            }
            if (MG_TREJ > 0 && zn && zs / zn > MG_TREJ) { __atomic_fetch_add(&pm.trej, 1, __ATOMIC_SEQ_CST); nrej += cw * ch; continue; }
        }
        /* P334: the frequency merge passes low-contrast motion (a face or a dark coat moving at high ISO: every DFT bin
           differs by little) -> ghosts. The cell motion weights of the spatial merge are computed here too, with a
           looser threshold (K x MG_FQK: clear motion only, small misalignment stays with the frequency merge), and
           scale the frame's frequency-merged cells (weight 0 = the cell keeps the reference and the other frames). */
        float K2c = MG_FQ ? K2 * MG_FQK * MG_FQK : K2;
        for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) {
            float dm = 0; WK[cy * 32 + cx] = 0;
            for (int j = 0; j < 3; ++j) for (int i = 0; i < 3; ++i) { int o = (cy + j) * 34 + cx + i; dm += Pk[o] - (float)Pr[o]; }
            float v = (float)Pr[(cy + 1) * 34 + cx + 1] * 0.25f;
            float sg = v > 64.f ? v - 64.f : 0.f;
            /* P252: + a relative error floor (alignment / resampling / remosaic differences between frames): in good
               light sensor noise alone made the test so strict that 15-84 % of cells were rejected */
            float var = mg.va * sg + mg.vb + (MG_REL * sg) * (MG_REL * sg);
            float z2 = dm * dm / (144.f * var);
            float d1 = Pk[(cy + 1) * 34 + cx + 1] - (float)Pr[(cy + 1) * 34 + cx + 1];
            float z1 = d1 * d1 / (16.f * var);
            if (MG_FINE && z1 > z2) z2 = z1;
            float wk = 1.f;
            if (z2 > K2c) { float q = 1.f + (z2 - K2c); wk = 1.f / (q * q); if (wk < 0.01f) { wk = 0; ++nrej; } }
            WK[cy * 32 + cx] = wk;
        }
        /* P257: the motion weights are smoothed over 3x3 cells (min of the cell and the neighbourhood mean), so a
           moving face does not turn into a patchwork of fully-merged and single-frame cells */
        for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) {
            float s = 0; int n = 0;
            for (int j = -1; j <= 1; ++j) for (int i = -1; i <= 1; ++i) { int yy = cy + j, xx = cx + i; if (yy < 0 || yy >= ch || xx < 0 || xx >= cw) continue; s += WK[yy * 32 + xx]; ++n; }
            float m = s / n, w0 = WK[cy * 32 + cx]; WS[cy * 32 + cx] = MG_WSM ? (w0 < m ? w0 : m) : w0;
        }
        if (MG_FQ && MG_FQW && MG_FQB > 0) {
            /* P334: low-contrast motion at high ISO is within the noise of a 3x3-cell test, but not of a 7x7-cell
               window (14x14 px): z = (sum of cell differences)^2 / (16 x sum of variances), signed, so texture and
               small misalignment average out and only a real brightness change of the area counts. Summed-area
               tables over the tile's cells; the window is clipped at the tile border. */
            double SD[33 * 33], SV[33 * 33];
            for (int i = 0; i <= cw; ++i) { SD[i] = 0; SV[i] = 0; }
            for (int cy = 0; cy < ch; ++cy) {
                double rd = 0, rv = 0; SD[(cy + 1) * 33] = 0; SV[(cy + 1) * 33] = 0;
                for (int cx = 0; cx < cw; ++cx) {
                    int o = (cy + 1) * 34 + cx + 1; float v = (float)Pr[o] * 0.25f, sg = v > 64.f ? v - 64.f : 0.f;
                    rd += Pk[o] - (float)Pr[o]; rv += mg.va * sg + mg.vb + (MG_REL * sg) * (MG_REL * sg);
                    SD[(cy + 1) * 33 + cx + 1] = SD[cy * 33 + cx + 1] + rd; SV[(cy + 1) * 33 + cx + 1] = SV[cy * 33 + cx + 1] + rv;
                }
            }
            for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) {
                int ya = cy - 3 < 0 ? 0 : cy - 3, yb = cy + 4 > ch ? ch : cy + 4, xa = cx - 3 < 0 ? 0 : cx - 3, xb = cx + 4 > cw ? cw : cx + 4;
                double d = SD[yb * 33 + xb] - SD[ya * 33 + xb] - SD[yb * 33 + xa] + SD[ya * 33 + xa];
                double v = SV[yb * 33 + xb] - SV[ya * 33 + xb] - SV[yb * 33 + xa] + SV[ya * 33 + xa];
                float zb = (float)(d * d / (16.0 * v + 1e-9));
                if (zb > MG_FQB) { float q = 1.f + (zb - MG_FQB) * (1.f / MG_FQB); float wb = 1.f / (q * q * q * q);
                    if (wb < WS[cy * 32 + cx]) WS[cy * 32 + cx] = wb < 0.01f ? 0.f : wb; }
            }
        }
        if (MG_FQ) { fq_tile(X0, Y0, tw, th, sx, sy, MG_FQW ? WS : 0); continue; }   /* P288 (+ P334 motion weights) */
        for (int cy = 0; cy < ch; ++cy) for (int cx = 0; cx < cw; ++cx) {
            float wk = WS[cy * 32 + cx];
            if (wk <= 0.005f) continue;
            if (MG_KR) {
                for (int j = 0; j < 2; ++j) for (int i = 0; i < 2; ++i) {
                    int X = X0 + 2 * cx + i, Y = Y0 + 2 * cy + j; float kw;
                    float kv = mg_kr(B, X, Y, sx, sy, &kw);
                    pm.acc[(i64)Y * OW + X] += wk * kv; pm.wtc[(i64)Y * OW + X] += wk * kw;
                }
                continue;
            }
            pm.wtc[(i64)(r0 + cy) * w0 + c0 + cx] += wk;
            for (int j = 0; j < 2; ++j) {
                float* a = pm.acc + (i64)(Y0 + 2 * cy + j) * OW + X0 + 2 * cx;
                const float* f = F + (2 * cy + j + 2) * MG_PW + 2 * cx + 2;
                a[0] += wk * f[0]; a[1] += wk * f[1];
            }
        }
    }
    mg.rej[ty] += nrej;
}
/* P251: where few frames were merged (rejected as motion / parallax) the result is as noisy as 1-3 frames and stands
   out as grainy patches next to well-merged areas -> a spatial same-colour filter (3x3 of the same colour, edge-
   preserving: range weight against the merged pixel's own noise), blended in by how far the merged weight W is
   below MG_LOWT x frames (as SCAMERA widens its kernel where few frames were accepted) */
#ifndef MG_LDJ
#define MG_LDJ 1                                          /* P269: colour-consistent (joint) low-count denoise */
#endif
static inline float pm_cell(int cx, int cy) {             /* merged 2x2 cell sum (R + Gr + Gb + B) */
    int x = 2 * mg_cl(cx, 0, mg.w0 - 1), y = 2 * mg_cl(cy, 0, mg.h0 - 1);
    const float* a = pm.acc + (i64)y * OW + x;
    return (a[0] + a[1] + a[OW] + a[OW + 1]) / pm.wtc[(i64)(y >> 1) * mg.w0 + (x >> 1)];
}
static float pm_lowdn(int x, int y, float v, float W, float amt, i64* cnt) {
    int w = mg.w, h = mg.h, px = x & 1, py = y & 1;
    float sw = 1.f, sv = v;
    if (MG_LDJ) {
        /* P269: the edge-preserving weights come from the 2x2 cell sums, so R, G and B of a cell are smoothed with the
           same weights; per-colour weights smoothed one colour across an edge and not the others -> colour fringes on
           moving objects (rickshaw, 2026-11-25). */
        int cx = x >> 1, cy = y >> 1; float S0 = pm_cell(cx, cy), m = 0.25f * S0;
        float var = 4.f * (mg.va * (m > 64.f ? m - 64.f : 0.f) + mg.vb) / W;
        float inv = 1.f / (2.f * 2.5f * 2.5f * var);
        for (int j = -1; j <= 1; ++j) for (int i = -1; i <= 1; ++i) {
            if (!i && !j) continue;
            int xx = mg_cl(x + 2 * i, px, w - 2 + px), yy = mg_cl(y + 2 * j, py, h - 2 + py);
            float Sn = pm_cell(xx >> 1, yy >> 1), dd = (Sn - S0) * (Sn - S0) * inv;
            float vn = pm.acc[(i64)yy * OW + xx] / pm.wtc[(i64)(yy >> 1) * mg.w0 + (xx >> 1)];
            float rw = (i && j ? 0.5f : 1.f) / (1.f + dd + 0.5f * dd * dd);
            sw += rw; sv += rw * vn;
        }
        ++*cnt;
        return v + amt * (sv / sw - v);
    }
    float var = (mg.va * (v > 64.f ? v - 64.f : 0.f) + mg.vb) / W;
    float inv = 1.f / (2.f * 2.5f * 2.5f * var);
    for (int j = -1; j <= 1; ++j) for (int i = -1; i <= 1; ++i) {
        if (!i && !j) continue;
        int xx = mg_cl(x + 2 * i, px, w - 2 + px), yy = mg_cl(y + 2 * j, py, h - 2 + py);
        float Wn = pm.wtc[(i64)(yy >> 1) * mg.w0 + (xx >> 1)];
        float vn = pm.acc[(i64)yy * OW + xx] / Wn, dd = (vn - v) * (vn - v) * inv;
        float rw = (i && j ? 0.5f : 1.f) / (1.f + dd + 0.5f * dd * dd);
        sw += rw; sv += rw * vn;
    }
    ++*cnt;
    return v + amt * (sv / sw - v);
}
/* P256: detail restore. Resampling the other frames onto the reference softens the finest detail (host test vs the
   true scene: response 0.85 / 0.67 / 0.50 in the three finest bands, a single frame 0.92 / 0.85 / 0.74), and GCam then
   denoises on top. A mild same-colour unsharp mask (3x3 of the same colour, weights 4/2/1) on the well-merged pixels
   puts part of it back; the merged noise is low enough to afford it. */
static float pm_detail(int x, int y, float v, float g) {
    int w = mg.w, h = mg.h, px = x & 1, py = y & 1;
    float s = 4.f * v;
    for (int j = -1; j <= 1; ++j) for (int i = -1; i <= 1; ++i) {
        if (!i && !j) continue;
        int xx = mg_cl(x + 2 * i, px, w - 2 + px), yy = mg_cl(y + 2 * j, py, h - 2 + py);
        float vn = pm.acc[(i64)yy * OW + xx] / pm.wtc[(i64)(yy >> 1) * mg.w0 + (xx >> 1)];
        s += (i && j ? 1.f : 2.f) * vn;
    }
    return v + g * MG_SHP * (v - s * (1.f / 16.f));   /* P257: tapered by the merged weight */
}
/* P314: output scale sc with a highlight knee: x = (v - 64) / 959, f = sc x + (1 - sc) x smoothstep((x - K) / (1 - K)),
   so f(1) = 1: clipped and near-clip pixels stay at the white level (GCam's saturation handling keeps light sources
   white instead of pink); midtones get the full scale. Monotone for sc in (0, 1). */
#ifndef PM_KNEE
#define PM_KNEE 0.6f
#endif
#ifndef PM_HLC
#define PM_HLC 1                                           /* P334: knee + detail per 2x2 cell (hue kept near clip) */
#endif
#ifndef PM_HLN
#define PM_HLN 990                                         /* P334: reference value that counts as near clip */
#endif
static inline float pm_knee(float v, float sc) {
    float x = (v - 64.f) * (1.f / 959.f); if (x <= 0.f) return 64.f + (v - 64.f) * sc;
    float t = (x - PM_KNEE) * (1.f / (1.f - PM_KNEE)); t = t < 0.f ? 0.f : (t > 1.f ? 1.f : t);
    float w = t * t * (3.f - 2.f * t);
    return 64.f + 959.f * (sc * x + (1.f - sc) * x * w);
}
static void pm_fin(int ty) {                                /* result -> frame 0 and the kept copy */
    int w = mg.w, h = mg.h, w0 = mg.w0;
    int y0 = ty * MG_T, y1 = y0 + MG_T > h ? h : y0 + MG_T;
    unsigned long long rng = 0x9e3779b97f4a7c15ULL * (unsigned long long)(ty + 7);
    float ws = 0; int nc = 0; i64 nlow = 0; float T = MG_LOWT * (float)pm.nmerged;
    /* P261: night brightening cap. GCam brightens the shot to its own plan from the frames' metadata; where our
       1/30 s + ISO cap left the frames far below that plan, the output is scaled down (x pm_night/256) so the final
       image is darker instead of pushed (the noise model GCam uses is scaled to match in the Java hook). */
    float sc = (pm_night > 0 && pm_night < 256) ? (float)pm_night / 256.f : 1.f;
    /* P334 highlight consistency: the knee and the detail boost used to work per pixel, i.e. per colour. Near clip
       (bright window, lamp) one colour of a 2x2 cell was clipped and kept at white while its neighbours were scaled
       down by the knee and sharpened on their own -> the colour ratios of the cell changed -> cyan / magenta fringes
       around windows. Now per 2x2 cell (R, Gr, Gb, B): one scale for all four from the cell's brightest value (a
       clipped value counts as white), so the hue of every cell is kept; no detail boost in cells that touch clip. */
    float V[2][8192]; unsigned char C[2][8192];
    for (int yp = y0; yp < y1; yp += 2) {
        int nr = yp + 1 < y1 ? 2 : 1;
        for (int j = 0; j < nr; ++j) {
            int y = yp + j; const u16* o = mg.buf[0] + (i64)y * OW;
            for (int x = 0; x < w; ++x) C[j][x] = o[x] >= 1020 ? 2 : (o[x] >= PM_HLN ? 1 : 0);
        }
        for (int j = 0; j < nr; ++j) {
            int y = yp + j; const u16* o = mg.buf[0] + (i64)y * OW;
            const float* a = pm.acc + (i64)y * OW; const float* q = MG_KR ? pm.wtc + (i64)y * OW : pm.wtc + (i64)(y >> 1) * w0;
            for (int x = 0; x < w; ++x) {
                if (C[j][x] == 2) { V[j][x] = (float)o[x]; continue; }        /* clipped: stays clipped */
                int xc = x & ~1, hot = 0;
                for (int jj = 0; jj < nr; ++jj) { hot |= C[jj][xc]; if (xc + 1 < w) hot |= C[jj][xc + 1]; }
                float W = q[MG_KR ? x : x >> 1], v = a[x] / W;
                if (!MG_KR && MG_LOWT > 0 && W < T) v = pm_lowdn(x, y, v, W, 0.5f * (T - W) / T, &nlow);   /* P258: at most half */
                if (!MG_KR && MG_SHP > 0 && !(PM_HLC && hot)) { float g = W / (0.75f * (float)pm.nmerged); v = pm_detail(x, y, v, g > 1.f ? 1.f : g); }
                V[j][x] = v;
            }
        }
        for (int x = 0; x < w; x += 2) {
            int xn = x + 1 < w ? 2 : 1;
            float k = sc;
            if (sc < 1.f) {
                if (PM_HLC) {
                    /* P335: the cell's mean (a clipped value counts as white), not its brightest value: with the max
                       every cell with one bright colour escaped the scale and GCam then lifted it x 1/sc (bright
                       shoe, 2026-11-27); the mean keeps the old per-pixel brightness on average */
                    float m = 0.f; int nm = 0;
                    for (int j = 0; j < nr; ++j) for (int i = 0; i < xn; ++i) { m += C[j][x + i] == 2 ? 1023.f : V[j][x + i]; ++nm; }
                    m /= (float)nm;
                    k = m > 64.5f ? (pm_knee(m, sc) - 64.f) / (m - 64.f) : sc;
                }
            }
            for (int j = 0; j < nr; ++j) {
                u16* o = mg.buf[0] + (i64)(yp + j) * OW;
                for (int i = 0; i < xn; ++i) {
                    int X = x + i; if (C[j][X] == 2) continue;
                    float v = V[j][X];
                    if (sc < 1.f) v = PM_HLC ? 64.f + (v - 64.f) * k : pm_knee(v, sc);
                    rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
                    float d = ((float)(u32)(rng >> 40 & 0xffffff) - (float)(u32)(rng >> 16 & 0xffffff)) * (0.5f / 16777216.f);
                    int iv = (int)(v + d + 0.5f); o[X] = (u16)(iv < 0 ? 0 : (iv > 1023 ? 1023 : iv));
                }
            }
        }
        for (int j = 0; j < nr; ++j) {
            int y = yp + j; const u16* o = mg.buf[0] + (i64)y * OW; u16* kk = pm.keep + (i64)y * OW;
            const float* q = MG_KR ? pm.wtc + (i64)y * OW : pm.wtc + (i64)(y >> 1) * w0;
            for (int x = 0; x < OW; ++x) kk[x] = o[x];        /* full row incl. padding */
            if (!(y & 1)) for (int x = 0; x < w0; ++x) { ws += q[MG_KR ? 2 * x : x]; ++nc; }
        }
    }
    for (int y = h; y < OH && ty == mg.ty - 1; ++y) { const u16* o = mg.buf[0] + (i64)y * OW; u16* kk = pm.keep + (i64)y * OW; for (int x = 0; x < OW; ++x) kk[x] = o[x]; }
    mg.wsum[ty] = ws; mg.wcnt[ty] = nc; __atomic_fetch_add(&pm.lowdn, nlow, __ATOMIC_SEQ_CST);
}
static void pm_item(int p, int i) {
    int kind = pm.ph_kind[p], fr = pm.ph_frame[p];
    if (fr > 0 && pm.skip == fr && kind != P_SETUP) return;
    int y0 = i * QB, y1 = y0 + QB > qj.h ? qj.h : y0 + QB;
    switch (kind) {
    case P_SHARP: {                                        /* frame i/16, band i%16: 4x4 luma gradient energy */
        int k = i / 16, b = i % 16; const u16* R = pm.reg[k]; int rsw = pm.regrs[k] / 2;
        int lw = pm.w / 4, lh = pm.h / 4, ly0 = lh / 16 + b * (lh * 7 / 8) / 16, ly1 = ly0 + (lh * 7 / 8) / 16;
        i64 g = 0; int prev[2048]; int cur[2048];
        for (int ly = ly0; ly < ly1; ++ly) {
            for (int lx = lw / 16; lx < lw - lw / 16; ++lx) {
                const u16* q = R + (i64)(4 * ly) * rsw + 4 * lx; int s4 = 0;
                for (int j = 0; j < 4; ++j) { const u16* r = q + (i64)j * rsw; s4 += r[0] + r[1] + r[2] + r[3]; }
                cur[lx] = s4;
                if (lx > lw / 16) { int d = s4 - cur[lx - 1]; g += d < 0 ? -d : d; }
                if (ly > ly0) { int d = s4 - prev[lx]; g += d < 0 ? -d : d; }
            }
            for (int lx = lw / 16; lx < lw - lw / 16; ++lx) prev[lx] = cur[lx];
        }
        pm.shp[k][b] = g; break; }
    case P_PICK: {
        i64 sh[MG_MAXF], mx = 0; int best = 0;
        for (int k = 0; k < pm.nreg; ++k) { sh[k] = 0; for (int b = 0; b < 16; ++b) sh[k] += pm.shp[k][b]; if (sh[k] > mx) { mx = sh[k]; best = k; } }
        /* order: sharpest first, then the rest by sharpness; below PM_SHMIN % of the best -> left out (keep >= 3) */
        int n = 0, taken[MG_MAXF] = {0};
        for (int j = 0; j < pm.nreg; ++j) { int bk = -1; for (int k = 0; k < pm.nreg; ++k) if (!taken[k] && (bk < 0 || sh[k] > sh[bk])) bk = k;
            taken[bk] = 1; pm.order[j] = bk; pm.shrel[j] = mx ? (int)(sh[bk] * 1000 / mx) : 1000;
            if (j < 3 || pm.shrel[j] >= PM_SHMIN * 10) ++n; }
        pm.nuse = n; (void)best;
#ifdef PM_FORCE0
        for (int j = 0; j < pm.nreg; ++j) pm.order[j] = j;   /* host test: registration order */
        pm.nuse = pm.nreg;
#endif
        break; }
    case P_SETUP: {
        if (fr >= pm.nuse) { pm.skip = fr; break; }
        int k = pm.order[fr];
        int rc = quad_prepare(pm.reg[k], pm.regrs[k], pm.wbits, pm.h, fr ? pm.tmp : mg.buf[0], 64);
        pm.skip = rc ? fr : 0; pm.cur = fr;
        if (!rc && (qj.w != pm.w || qj.h != pm.h || qj.mode != pm.mode)) pm.skip = fr;
        break; }
    case P_QSC: q_qscrow(y0, y1); break;
    case P_A: q_passA(y0 / 2, (y1 + 1) / 2); break;
    case P_M: q_passM(y0 / 2, (y1 + 1) / 2); break;
    case P_C: q_passC(y0, y1); break;
    case P_XC: q_copy(y0, y1); break;
    case P_D1: q_dn1(y0 / 2, y1 / 2); break;
    case P_D2: q_dn2(y0 / 4, y1 / 4); break;
    case P_D3: q_dn3(y0 / 4, y1 / 4); break;
    case P_D4: q_dn4(y0 / 2, y1 / 2); break;
    case P_NZ: {
        if (fr <= 1) {                                     /* noise from the first two slots */
            if (__atomic_exchange_n(&nz_have_reset, 0, __ATOMIC_SEQ_CST)) nz_reset();
            nz_measure(fr ? pm.tmp : mg.buf[0], pm.w, pm.h);
            if (nzfit && fr) { mg.va = (float)(nzS * 959.0); mg.vb = (float)(nzO * 959.0 * 959.0); }
            if (mg.va < 0.05f) mg.va = 0.05f;
            if (mg.vb < 0.25f) mg.vb = 0.25f;
        }
        break; }
    case P_L0: pm_rowL(i, 0); break;
    case P_INIT: pm_init(i); break;
    case P_L: pm_rowL(i, 1); break;
    case P_G: mg_global(); break;
    case P_TA: mg_tilesA(i); break;
    case P_MED: mg_global2(); break;
    case P_TA2: mg_tilesA2(i); break;
    case P_FIT: mg_fit(); if (mg_fitn) { if (MG_REFINE) mg_refine(); pm.refx += mg_refoff[0] < 0 ? -mg_refoff[0] : mg_refoff[0]; pm.refy += mg_refoff[1] < 0 ? -mg_refoff[1] : mg_refoff[1]; pm.fitn += mg_fitn; pm.fitres += mg_fitres; ++pm.nfit; } break;
    case P_ACC: pm_acc(i); if (i == 0) ++pm.nmerged; break;
    case P_FIN: pm_fin(i); break;
    case P_DSH: ds_rows(i); break;
    case P_DSV: ds_cols(i); break;
    case P_DSC: {
        int a = i * 32, b = a + 32 > OH ? OH : a + 32;
        for (int y = a; y < b; ++y) { const u16* s2 = pm.keep + (i64)y * OW; u16* d = mg.buf[0] + (i64)y * OW; for (int x = 0; x < OW; ++x) d[x] = s2[x]; }
        break; }
    case P_COPY: {
        int a = i * 32, b = a + 32 > OH ? OH : a + 32;
        for (int y = a; y < b; ++y) { const u16* s = pm.keep + (i64)y * OW; u16* d = mg.buf[0] + (i64)y * OW; for (int x = 0; x < OW; ++x) d[x] = s[x]; }
        break; }
    }
}

/* every worker thread and the caller */
static void pm_work(void) {
    { i64 z = 0; i64 now = mg_ms(); __atomic_compare_exchange_n(&pm.t0, &z, now ? now : 1, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST); }
    int it;
    while ((it = __atomic_fetch_add(&pm.next, 1, __ATOMIC_SEQ_CST)) < pm.total) {
        int p = 0; while (p + 1 < pm.nph && pm.ph_start[p + 1] <= it) ++p;
        if (p > 0) q_wait(&pm.done[p - 1], pm.ph_n[p - 1]);
        pm_item(p, it - pm.ph_start[p]);
        __atomic_fetch_add(&pm.done[p], 1, __ATOMIC_SEQ_CST);
    }
}
static void pm_finish(void) {
    if (pm.job == 1) {
        pm.state = 2;
        double ws = 0; i64 nc = 0, nr = 0;
        for (int i = 0; i < mg.ty; ++i) { ws += mg.wsum[i]; nc += mg.wcnt[i]; nr += mg.rej[i]; }
        char* o = mg_txt;
        mg_put(&o, "premerge frames="); mg_int(&o, pm.nmerged); mg_put(&o, "/"); mg_int(&o, pm.nreg);
        mg_put(&o, " eff="); mg_int(&o, nc ? (i64)(ws * 100 / nc) : 0); mg_put(&o, "/100");
        mg_put(&o, " rej="); mg_int(&o, (nc && pm.nmerged > 1) ? nr * 1000 / (nc * (pm.nmerged - 1)) : 0); mg_put(&o, "/1000");
        mg_put(&o, " K="); mg_int(&o, mg.K10);
        mg_put(&o, " noise="); mg_int(&o, (i64)(mg.va * 1000)); mg_put(&o, ","); mg_int(&o, (i64)(mg.vb * 100));
        mg_put(&o, " ms="); mg_int(&o, pm.t0 ? mg_ms() - pm.t0 : -1);
        mg_put(&o, " fit="); mg_int(&o, pm.nfit); mg_put(&o, "x"); mg_int(&o, pm.nfit ? pm.fitn / pm.nfit : 0); mg_put(&o, " res="); mg_int(&o, pm.nfit ? pm.fitres / pm.nfit : -1);
        mg_put(&o, " local="); mg_int(&o, pm.nfit ? pm.lockeep / pm.nfit : 0);
        mg_put(&o, " trej="); mg_int(&o, pm.trej);
        mg_put(&o, " night="); mg_int(&o, pm_night ? pm_night : 256);
        if (pm_ds) { mg_put(&o, " out="); mg_int(&o, ds_w2); mg_put(&o, "x"); mg_int(&o, ds_h2); }
        mg_put(&o, " lowdn="); mg_int(&o, pm.lowdn * 1000 / ((i64)mg.w * mg.h + 1));
        { /* P303: highlight check on the reference raw frame (sampled): per 10000 pixels >= 1015 (sensor clip) and >= 900 */
          const u16* r = pm.reg[pm.ref]; int rsw = pm.regrs[pm.ref] / 2; i64 nt = 0, nc1 = 0, nc2 = 0;
          if (r) for (int y = 8; y < pm.h - 8; y += 7) { const u16* p = r + (i64)y * rsw;
              for (int x = 8; x < pm.w - 8; x += 5) { int v = p[x]; ++nt; if (v >= 1015) ++nc1; if (v >= 900) ++nc2; } }
          mg_put(&o, " clip="); mg_int(&o, nt ? nc1 * 10000 / nt : -1); mg_put(&o, ","); mg_int(&o, nt ? nc2 * 10000 / nt : -1); }
        mg_put(&o, " sharp="); for (int j = 0; j < pm.nreg; ++j) { if (j) mg_put(&o, ","); mg_int(&o, pm.shrel[j] / 10); if (j == pm.nuse - 1) mg_put(&o, "|"); }
        *o = 0;
        pm.tmp = 0;                                       /* now only pm.keep (same buffer) */
        pm_lastdim = pm_ds ? (ds_w2 << 16 | ds_h2) : 0;
        pm_munmap(pm.acc, PM_ACC); pm.acc = 0; pm_munmap(pm.wtc, PM_WTC); pm.wtc = 0;
        pm.ncopied = 1;
    } else if (pm.job == 2) {
        ++pm.ncopied;
        pm_lastdim = pm_ds ? (ds_w2 << 16 | ds_h2) : 0;
        char* o = mg_txt; mg_put(&o, "premerge copy "); mg_int(&o, pm.ncopied); mg_put(&o, "/"); mg_int(&o, pm.nreg + pm_nx); *o = 0;
        if (pm.ncopied >= pm.nreg + pm_nx) { pm_free(); pm.armed = 0; }
    }
    pm_lastjob = pm.job; pm.job = 0;
}
