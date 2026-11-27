/* XENIUS tbin: 200 MP RGGB RAW16 -> 50 MP Bayer for HDR+ (P176).
   Adaptive by ISO (t256 = smooth share, 0..256, chosen by the Java helper):
     t256 = 0    Natural QB 2x bin (natural.c, C port of RawR NaturalBayerBin.h, GPL-3.0) - quad-Bayer artifact
                 suppression for good light (trees / backlight)
     t256 = 256  smooth same-colour binomial 2x bin (1 4 6 4 1 / 1 3 3 1) - high ISO noise
     between     blend of the two
   then a same-colour linear stretch to 8192x6144 (8160 -> 8192 = 0.4 %, 6128 -> 6144 = 0.26 %), CFA phase kept.
   Natural QB runs on several threads: prepare (b) -> work (w) on every thread -> finish (f).
   Freestanding: no libc; JNI through the function table. This file is GPL-3.0 (includes natural.c). */
#ifndef DITH
#define DITH 1.5f
#endif
typedef unsigned short u16; typedef unsigned int u32; typedef long long i64;
#define OW 8192
#define OH 6144
static inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
#include "natural.c"
#include "quad.c"
#include "merge.c"

/* one binned row of binned-row index y into out[0..bw).
   sharp: RawR BayerBin.h kernel (5/4 taps, local min/max clamp); smooth: same-colour binomial kernel.
   t256 = blend weight of the smooth result. Both keep the CFA phase. */
static void bin_row(const u16* src, int rsw, int sw, int sh, int y, float* out, int t256) {
    int bw = sw / 2;
    int ys[5], wy[5], gy[5], ny, py = y & 1, cy = 2 * y;
    if (py) { ys[0]=cy-3; ys[1]=cy-1; ys[2]=cy+1; ys[3]=cy+3; wy[0]=1; wy[1]=19; wy[2]=19; wy[3]=1; gy[0]=1; gy[1]=3; gy[2]=3; gy[3]=1; ny=4; }
    else { ys[0]=cy-4; ys[1]=cy-2; ys[2]=cy; ys[3]=cy+2; ys[4]=cy+4; wy[0]=wy[4]=-2; wy[1]=wy[3]=5; wy[2]=14; gy[0]=gy[4]=1; gy[1]=gy[3]=4; gy[2]=6; ny=5; }
    const u16* rows[5];
    for (int j = 0; j < ny; ++j) rows[j] = src + (i64)clampi(ys[j], py, sh - 2 + py) * rsw;
    float dy = py ? 40.f : 20.f, gdy = py ? 8.f : 16.f;
    float ts = (float)t256 / 256.f;
    for (int x = 0; x < bw; ++x) {
        int px = x & 1, cx = 2 * x;
        int xs[5], wx[5], gx[5], nx;
        if (px) { xs[0]=cx-3; xs[1]=cx-1; xs[2]=cx+1; xs[3]=cx+3; wx[0]=1; wx[1]=19; wx[2]=19; wx[3]=1; gx[0]=1; gx[1]=3; gx[2]=3; gx[3]=1; nx=4; }
        else { xs[0]=cx-4; xs[1]=cx-2; xs[2]=cx; xs[3]=cx+2; xs[4]=cx+4; wx[0]=wx[4]=-2; wx[1]=wx[3]=5; wx[2]=14; gx[0]=gx[4]=1; gx[1]=gx[3]=4; gx[2]=6; nx=5; }
        if (x < 2 || x >= bw - 2) for (int i = 0; i < nx; ++i) xs[i] = clampi(xs[i], px, sw - 2 + px);
        int sum = 0, gsum = 0, lo = 65535, hi = 0;
        for (int j = 0; j < ny; ++j) {
            const u16* r = rows[j]; int rsum = 0, grs = 0;
            for (int i = 0; i < nx; ++i) { int v = r[xs[i]]; rsum += wx[i] * v; grs += gx[i] * v; lo = v < lo ? v : lo; hi = v > hi ? v : hi; }
            sum += wy[j] * rsum; gsum += gy[j] * grs;
        }
        float v = (float)sum / ((px ? 40.f : 20.f) * dy);
        if (v < lo) v = lo; if (v > hi) v = hi;
        if (t256 > 0) { float g = (float)gsum / ((px ? 8.f : 16.f) * gdy); v = v + (g - v) * ts; }
        out[x] = v;
    }
}

/* smooth same-colour binomial bin of binned row y, columns [x0, x1) -> out[0 .. x1-x0) (codes) */
static void bin_seg(const u16* src, int rsw, int sw, int sh, int y, int x0, int x1, float* out) {
    int bw = sw / 2;
    int ys[5], gy[5], ny, py = y & 1, cy = 2 * y;
    if (py) { ys[0]=cy-3; ys[1]=cy-1; ys[2]=cy+1; ys[3]=cy+3; gy[0]=1; gy[1]=3; gy[2]=3; gy[3]=1; ny=4; }
    else { ys[0]=cy-4; ys[1]=cy-2; ys[2]=cy; ys[3]=cy+2; ys[4]=cy+4; gy[0]=gy[4]=1; gy[1]=gy[3]=4; gy[2]=6; ny=5; }
    const u16* rows[5];
    for (int j = 0; j < ny; ++j) rows[j] = src + (i64)clampi(ys[j], py, sh - 2 + py) * rsw;
    float gdy = py ? 8.f : 16.f;
    for (int x = x0; x < x1; ++x) {
        int px = x & 1, cx = 2 * x;
        int xs[5], gx[5], nx;
        if (px) { xs[0]=cx-3; xs[1]=cx-1; xs[2]=cx+1; xs[3]=cx+3; gx[0]=1; gx[1]=3; gx[2]=3; gx[3]=1; nx=4; }
        else { xs[0]=cx-4; xs[1]=cx-2; xs[2]=cx; xs[3]=cx+2; xs[4]=cx+4; gx[0]=gx[4]=1; gx[1]=gx[3]=4; gx[2]=6; nx=5; }
        if (x < 2 || x >= bw - 2) for (int i = 0; i < nx; ++i) xs[i] = clampi(xs[i], px, sw - 2 + px);
        int gsum = 0;
        for (int j = 0; j < ny; ++j) { const u16* r = rows[j]; int g = 0; for (int i = 0; i < nx; ++i) g += gx[i] * r[xs[i]]; gsum += gy[j] * g; }
        out[x - x0] = (float)gsum / ((px ? 8.f : 16.f) * gdy);
    }
}

#define MAXBW 8192
static float cache[4][MAXBW];
static int xi0[OW], xi1[OW]; static float xf[OW];
static float rowtmp[OW];
static struct { const u16* src; int rs, sw, sh; u16* dst; int black, white, t256, wbp, ok, bw, bh, small, quad; } tj;

/* step 1: validate + set up (Natural QB job when t256 < 256) */
int tbin_prepare(const u16* src, int rs, int sw, int sh, u16* dst, int black, int white, int t256, int wbp) {
    tj.quad = 0;
    tj.ok = 0;
    nb_job.bands = 0; __atomic_store_n(&nb_next, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&nb_slot, 0, __ATOMIC_SEQ_CST);
    if (sw < 64 || sh < 64 || (sw & 3) || (sh & 3) || rs < sw * 2) return 2;
    if (sw / 2 > OW || sh / 2 > OH || sw / 2 > MAXBW) return 3;
    tj.src = src; tj.rs = rs; tj.sw = sw; tj.sh = sh; tj.dst = dst; tj.black = black; tj.white = white;
    tj.t256 = t256 < 0 ? 0 : (t256 > 256 ? 256 : t256); tj.wbp = wbp;
    {
        float wb[3] = {(float)(wbp & 0xffff) / 1000.f, 1.f, (float)((wbp >> 16) & 0xffff) / 1000.f};
        if (wb[0] < 0.2f || wb[0] > 8.f) wb[0] = 1.8f;
        if (wb[2] < 0.2f || wb[2] > 8.f) wb[2] = 2.2f;
        nb_prepare(src, rs, sw, sh, dst, OW, (float)black, (float)white, wb, tj.t256);   /* bands: Natural / smooth / blend */
    }
    tj.bw = sw / 2; tj.bh = sh / 2; tj.small = 0;
    {   /* Some captures arrive as a binned-mode frame (sw/4 x sh/4, e.g. 4080x3064) in the top-left of the 200 MP
           buffer, the rest zero. Detect it (or a sw/2 x sh/2 frame) and pass that frame on instead of binning:
           4x codes into dst, the finish stretch then scales it to 8192x6144. */
        const u16* s = src; int rsw = rs / 2; int nz4 = 0, nz2 = 0;
        for (int y = 16; y < sh; y += 97)
            for (int x = 16; x < sw; x += 89) {
                if (y < sh / 4 + 8 && x < sw / 4 + 8) continue;
                int v = s[(i64)y * rsw + x];
                if (v) { ++nz4; if (y >= sh / 2 + 8 || x >= sw / 2 + 8) ++nz2; }
            }
        int f = nz4 == 0 ? 4 : (nz2 == 0 ? 2 : 1);
        if (f > 1) {
            int cw = sw / f, ch = sh / f;
            for (int y = 0; y < ch; ++y) {
                const u16* r = s + (i64)y * rsw; u16* o = dst + (i64)y * OW;
                for (int x = 0; x < cw; ++x) { int v = r[x] * 4; o[x] = (u16)(v > 65535 ? 65535 : v); }
            }
            tj.bw = cw; tj.bh = ch; tj.small = f;
            nb_job.bands = 0;                                        /* workers have nothing to do */
        }
    }
    tj.ok = 1;
    return 0;
}

/* step 2: on every worker thread and on the caller */
void tbin_work(void) { if (tj.ok) { if (tj.quad) { if (pm.job) pm_work(); else { quad_work(); mg_work(); } } else nb_work(); } }
/* native quad 50 MP (main camera, sensor mode 3) -> Bayer, same w/f thread protocol */
int quad_start(const u16* src, int rs, int w, int h, u16* dst) {
    if (!q_take()) return 22;
    tj.ok = 0; tj.quad = 1;
    int rc = quad_prepare(src, rs, w, h, dst, 64); if (rc) { tj.quad = 0; q_drop(); return rc; }
    if (!pm_start(src, dst, w)) mg_frame(dst);     /* P247 pre-merge / copy; P246 last-frame merge */
    tj.ok = 1; return 0;
}

/* step 3: after all workers returned: blend + stretch, in place (descending rows: every source row used by
   dest row y is <= y, and the binned image sits top-left in dst) */
int tbin_finish(void) {
    if (tj.quad) { int ok = tj.ok; pm_lastjob = 0; if (pm.job) pm_finish(); mg_finish(); tj.ok = 0; tj.quad = 0; q_drop(); return ok ? 0 : 1; }
    if (!tj.ok) return 4;
    const u16* src = tj.src; int sw = tj.sw, sh = tj.sh, t256 = tj.t256; u16* dst = tj.dst;
    int bw = tj.bw, bh = tj.bh, rsw = tj.rs / 2;
    int cidx[4] = {-1, -1, -1, -1}; int cnext = 0;
    int Lbw = bw / 2, Ldw = OW / 2, Lbh = bh / 2, Ldh = OH / 2;
    for (int x = 0; x < OW; ++x) {
        int p = x & 1, j = x >> 1;
        float t = (float)j * (float)(Lbw - 1) / (float)(Ldw - 1);
        int k0 = (int)t; if (k0 > Lbw - 1) k0 = Lbw - 1;
        int k1 = k0 + 1 < Lbw ? k0 + 1 : Lbw - 1;
        xi0[x] = 2 * k0 + p; xi1[x] = 2 * k1 + p; xf[x] = t - (float)k0;
    }
    (void)src; (void)rsw; (void)cidx; (void)cnext; (void)t256;
    static unsigned long long seed = 0x9e3779b97f4a7c15ULL; seed += 0xd1b54a32d192ed03ULL;
    unsigned long long rng = seed;
    for (int y = OH - 1; y >= 0; --y) {
        int p = y & 1, j = y >> 1;
        float t = (float)j * (float)(Lbh - 1) / (float)(Ldh - 1);
        int k0 = (int)t; if (k0 > Lbh - 1) k0 = Lbh - 1;
        int k1 = k0 + 1 < Lbh ? k0 + 1 : Lbh - 1;
        float fy = t - (float)k0;
        const u16* n0 = dst + (i64)(2 * k0 + p) * OW; const u16* n1 = dst + (i64)(2 * k1 + p) * OW;
        for (int x = 0; x < OW; ++x) {
            float a = n0[xi0[x]] + (n0[xi1[x]] - n0[xi0[x]]) * xf[x];
            float b = n1[xi0[x]] + (n1[xi1[x]] - n1[xi0[x]]) * xf[x];
            rowtmp[x] = (a + (b - a) * fy) * 0.25f;                              /* binned image is in 4x codes */
        }
        u16* out = dst + (i64)y * OW;
        /* TPDF dither (+-DITH codes) before rounding to 10-bit codes: the vendor 200 MP RAW is denoised to well under
           one code of noise, so smooth dark gradients (vignetting under the lens-shading gain) quantize into 1-code
           steps that HDR+ lifts into coloured contour rings; the dither keeps the binned sub-code mean and lets HDR+
           merge/denoise turn the steps back into gradients. New sequence for every frame. */
        for (int x = 0; x < OW; ++x) {
            rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
            float d = ((float)(u32)(rng >> 40 & 0xffffff) - (float)(u32)(rng >> 16 & 0xffffff)) * (DITH / 16777216.f);
            float v = rowtmp[x];
            int iv = v >= (float)tj.white - 0.5f ? tj.white : (int)(v + d + 0.5f);       /* clipped stays exactly white */
            out[x] = (u16)(iv < 0 ? 0 : (iv > tj.white ? tj.white : iv));
        }
    }
#ifdef TBDUMP
    {   /* log build: binned 8192x6144 RAW16 (RGGB, black 64, white 1023) -> Download/tb_dump.raw (last frame wins) */
        static const char path[] = "/storage/emulated/0/Download/tb_dump.raw";
        register long x0 __asm__("x0") = -100; register long x1 __asm__("x1") = (long)path;
        register long x2 __asm__("x2") = 01 | 0100 | 01000; register long x3 __asm__("x3") = 0644;
        register long x8 __asm__("x8") = 56;                                      /* openat */
        __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
        long fd = x0;
        if (fd >= 0) {
            const char* p = (const char*)dst; long left = (long)OW * OH * 2;
            while (left > 0) {
                register long a0 __asm__("x0") = fd; register long a1 __asm__("x1") = (long)p;
                register long a2 __asm__("x2") = left > (1L << 24) ? (1L << 24) : left; register long a8 __asm__("x8") = 64;
                __asm__ volatile("svc 0" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a8) : "memory");
                if (a0 <= 0) break; p += a0; left -= a0;
            }
            register long c0 __asm__("x0") = fd; register long c8 __asm__("x8") = 57;
            __asm__ volatile("svc 0" : "+r"(c0) : "r"(c8) : "memory");
        }
    }
#endif
    tj.ok = 0;
    return 0;
}

int tbin_run(const u16* src, int rs, int sw, int sh, u16* dst, int black, int white, int t256, int wbp) {
    int rc = tbin_prepare(src, rs, sw, sh, dst, black, white, t256, wbp); if (rc) return rc;
    tbin_work(); return tbin_finish();
}

#ifndef HOST_TEST
typedef void* jobject; typedef const void* const* JNIEnv;
typedef void* (*GetAddr)(JNIEnv*, jobject);
typedef i64 (*GetCap)(JNIEnv*, jobject);
void* memset(void* d, int c, unsigned long n) { unsigned char* p = d; while (n--) *p++ = (unsigned char)c; return d; }
void* memcpy(void* d, const void* s, unsigned long n) { unsigned char* p = d; const unsigned char* q = s; while (n--) *p++ = *q++; return d; }
static const u16* js; static int jrs, jw, jh; static u16* jd;
/* N.b(src, rowStride, w, h, dst, t256, wbp): prepare */
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_b(JNIEnv* env, jobject cls, jobject src, int rs, int w, int h, jobject dst, int t256, int wbp) {
    GetAddr addr = (GetAddr)(*env)[230]; GetCap cap = (GetCap)(*env)[231];
    const u16* s = (const u16*)addr(env, src); u16* d = (u16*)addr(env, dst);
    js = 0;
    if (!s || !d) return 10;
    if (cap(env, dst) < (i64)OW * OH * 2) return 11;
    if (cap(env, src) < (i64)rs * (h - 1) + (i64)w * 2) return 12;
    js = s; jrs = rs; jw = w; jh = h; jd = d;
    return tbin_prepare(s, rs, w, h, d, 64, 1023, t256, wbp);
}
/* N.q(src, rowStride, w, h, dst): prepare the quad -> Bayer remosaic (then N.w on every thread, N.f) */
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_q(JNIEnv* env, jobject cls, jobject src, int rs, int w, int h, jobject dst) {
    GetAddr addr = (GetAddr)(*env)[230]; GetCap cap = (GetCap)(*env)[231];
    const u16* s = (const u16*)addr(env, src); u16* d = (u16*)addr(env, dst);
    js = 0;
    if (!s || !d) return 10;
    if (cap(env, dst) < (i64)OW * OH * 2) return 11;
    if (cap(env, src) < (i64)rs * (OH - 1) + (i64)OW * 2) return 12;
    js = s; jrs = rs; jw = w; jh = h; jd = d;
    return quad_start(s, rs, w, h, d);
}
typedef jobject (*NewDBB)(JNIEnv*, void*, i64);
/* N.a(): a pool buffer (8192 x 6144 RAW16) as a direct ByteBuffer, or null */
__attribute__((visibility("default"))) jobject Java_TemporalBinning_00024N_a(JNIEnv* env, jobject cls) {
    void* p = q_acquire(); if (!p) return 0;
    return ((NewDBB)(*env)[229])(env, p, (i64)OW * OH * 2);
}
/* N.r(buffer): release a pool buffer (ignored for any other buffer); returns slots still in use */
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_r(JNIEnv* env, jobject cls, jobject buf) {
    GetAddr addr = (GetAddr)(*env)[230];
    void* p = buf ? addr(env, buf) : 0;
    if (p) q_release(p);
    return q_inuse();
}
/* N.n(frames, K x 10): a 50 MP burst of that many frames starts (P246 merge) */
__attribute__((visibility("default"))) void Java_TemporalBinning_00024N_n(JNIEnv* env, jobject cls, int n, int k) { pm_ds = k / 1000000; k %= 1000000; int k10 = k % 1000; pm_night = k / 1000; mg_begin(0, k10); pm_begin(n, k10); }
/* N.p(buffer, rowStride): a raw 50 MP frame of the coming shot (P247 pre-merge) -> frames registered, or -1 */
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_p(JNIEnv* env, jobject cls, jobject buf, int rs) {
    GetAddr addr = (GetAddr)(*env)[230]; GetCap cap = (GetCap)(*env)[231];
    u16* p = buf ? (u16*)addr(env, buf) : 0;
    if (!p || rs < OW * 2 || cap(env, buf) < (i64)rs * (OH - 1) + (i64)OW * 2) return -2;
    return pm_register(p, rs);
}
/* N.d(): P271 output size of the frame just finished (w << 16 | h), 8192 x 6144 unless downscaled */
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_d(JNIEnv* env, jobject cls) { int d = pm_lastdim; pm_lastdim = 0; return d ? d : (8192 << 16 | 6144); }
/* N.w(): work (any thread) */
__attribute__((visibility("default"))) void Java_TemporalBinning_00024N_w(JNIEnv* env, jobject cls) { tbin_work(); }
/* ---- burst noise measurement (log only): consecutive frames of a burst, green (x+y odd) samples of 32x32 blocks on a
   128 px grid; per block the mean and the temporal difference variance var(cur - prev) / 2; per signal bin the 25th
   percentile (flat, static blocks); weighted fit var = S x + O in GCam / Camera2 units (x = (v - 64) / 959, var / 959^2) ---- */
#define NB_GX 64
#define NB_GY 48
#define NZ_N 512
static u16 nz_prev[NB_GX * NB_GY * NZ_N];
static int nz_have, nz_frames; static i64 nz_prevsum;
static char nz_txt[800];
static float nz_m[NB_GX * NB_GY], nz_v[NB_GX * NB_GY];
static void nz_puti(char** p, i64 v) { char t[24]; int n = 0; if (v < 0) { *(*p)++ = '-'; v = -v; } do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v); while (n) *(*p)++ = t[--n]; }
static void nz_puts(char** p, const char* s) { while (*s) *(*p)++ = *s++; }
static void nz_reset(void) { nz_have = 0; }
static void nz_measure(const u16* d, int w, int h) {
    char* o = nz_txt; nz_txt[0] = 0;
    int nb = 0; i64 tot = 0;
    for (int by = 0; by < NB_GY; ++by) for (int bx = 0; bx < NB_GX; ++bx) {
        int x0 = bx * 128 + 48, y0 = by * 128 + 48; if (x0 + 32 > w || y0 + 32 > h) continue;
        u16* pv = nz_prev + (i64)(by * NB_GX + bx) * NZ_N; int k = 0; i64 s = 0, sd = 0, sd2 = 0; int clip = 0;
        for (int y = 0; y < 32; ++y) for (int x = (y & 1) ^ 1; x < 32; x += 2) {
            int v = d[(i64)(y0 + y) * OW + x0 + x]; if (v >= 1000) clip = 1;
            s += v; int df = v - pv[k]; sd += df; sd2 += (i64)df * df; pv[k] = (u16)v; ++k;
        }
        tot += s;
        if (nz_have && !clip) { float m = (float)s / k, md = (float)sd / k; nz_m[nb] = m; nz_v[nb] = ((float)sd2 / k - md * md) * 0.5f; ++nb; }
    }
    int was = nz_have; i64 ps = nz_prevsum; nz_prevsum = tot; nz_have = 1;
    if (!was) { nz_frames = 1; nz_puts(&o, "noise first"); *o = 0; return; }
    if (ps <= 0 || (tot - ps) * 10 > ps || (ps - tot) * 10 > ps) { nz_frames = 1; nz_puts(&o, "noise newburst"); *o = 0; return; }
    ++nz_frames;
    /* 12 signal bins over x in (0, 1) (log spaced from 0.004), 25th percentile of the variance in each */
    double sw = 0, sx = 0, sy = 0, sxx = 0, sxy = 0; int used = 0;
    for (int b = 0; b < 12; ++b) {
        float lo = 0.004f, hi = 0.004f; for (int i = 0; i < b; ++i) lo *= 1.6f; hi = lo * 1.6f;
        static float tmp[NB_GX * NB_GY]; int n = 0; double xs = 0;
        for (int i = 0; i < nb; ++i) { float x = (nz_m[i] - 64.f) / 959.f; if (x >= lo && x < hi) { tmp[n++] = nz_v[i]; xs += x; } }
        if (n < 6) continue;
        int q = n / 4; /* partial selection of the q-th smallest */
        { int lo2 = 0, hi2 = n - 1;                                  /* quickselect: tmp[q] = q-th smallest */
          while (lo2 < hi2) { float pv2 = tmp[(lo2 + hi2) >> 1]; int i = lo2, j = hi2;
            while (i <= j) { while (tmp[i] < pv2) ++i; while (tmp[j] > pv2) --j; if (i <= j) { float t = tmp[i]; tmp[i] = tmp[j]; tmp[j] = t; ++i; --j; } }
            if (q <= j) hi2 = j; else if (q >= i) lo2 = i; else break; } }
        double x = xs / n, y = 1.045 * tmp[q] / (959.0 * 959.0)   /* 25th pct of a 512-sample variance ~ 0.957 of the mean */, wgt = n / (y * y + 1e-18);
        sw += wgt; sx += wgt * x; sy += wgt * y; sxx += wgt * x * x; sxy += wgt * x * y; ++used;
        if (used <= 12) { nz_puts(&o, used == 1 ? "noise bins" : ""); nz_puts(&o, " "); nz_puti(&o, (i64)(x * 1000)); nz_puts(&o, ":"); nz_puti(&o, (i64)(y * 1e9)); }
    }
    if (used >= 2) {
        double den = sw * sxx - sx * sx, S = den != 0 ? (sw * sxy - sx * sy) / den : 0, O = (sy - S * sx) / sw;
        nzS = S; nzO = O; nzfit = S > 0 && O > -1e-3;                    /* P246: the merge's noise model */
        nz_puts(&o, " | fit S="); nz_puti(&o, (i64)(S * 1e9)); nz_puts(&o, "e-9 O="); nz_puti(&o, (i64)(O * 1e9)); nz_puts(&o, "e-9 frames=");
        nz_puti(&o, nz_frames);
    } else nz_puts(&o, "noise nofit");
    *o = 0;
}
typedef jobject (*NewStrUTF)(JNIEnv*, const char*);
/* N.s(): the last burst noise line */
__attribute__((visibility("default"))) jobject Java_TemporalBinning_00024N_s(JNIEnv* env, jobject cls) {
    return ((NewStrUTF)(*env)[167])(env, nz_txt);
}
/* N.f(): finish -> rc | source mean << 8 | output mean << 20 */
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_f(JNIEnv* env, jobject cls) {
    int tj_was_quad = tj.quad;
    int rc = tbin_finish();
    const u16* s = js; u16* d = jd; int w = jw, h = jh, rs = jrs;
    if (rc || !s) return rc ? rc : 13;
    /* no read of the source here: GCam may already have closed / unmapped the input buffer (crash 2026-11-22,
       SEGV_ACCERR in this function). Statistics come from our own output buffer only. */
    (void)w; (void)h; (void)rs;
    if (tj_was_quad && !pm_lastjob) nz_measure(d, w, h);
    if (mg_txt[0]) { char* o = nz_txt; while (*o) ++o; nz_puts(&o, " | "); for (const char* m = mg_txt; *m && o < nz_txt + sizeof(nz_txt) - 1; ) *o++ = *m++; *o = 0; mg_txt[0] = 0; }
    i64 dsum = 0;
    for (int y = 8; y < OH; y += 131) for (int x = 8; x < OW; x += 127) dsum += d[(i64)y * OW + x];
    int dmean = (int)(dsum / ((i64)((OH - 8 + 130) / 131) * ((OW - 8 + 126) / 127)));
    return rc | (dmean & 4095) << 8 | (dmean & 4095) << 20;
}

/* ---- P310 viewfinder AE meter (log only): RAW16 frame, 4x4 tiles on a ~128x96 grid (layout-agnostic: tile mean and
   tile max pixel). Black 64, white 1023. Rate limited to one frame per 300 ms. Returns a text line or null. ---- */
static float ae_log2(float x) { union { float f; u32 i; } u = { x }; float e = (float)(int)((u.i >> 23) & 255) - 127.f;
    u.i = (u.i & 0x007fffff) | 0x3f800000; float m = u.f; /* m in [1,2) */
    return e + (m - 1.f) * (1.4425f - 0.4425f * (m - 1.f)); }
static i64 ae_last; static char ae_txt[400]; static float ae_medt, ae_grd, ae_hs = 256.f;
#ifndef AE_HC
#define AE_HC 40.f
#endif
#ifndef AE_HMAX
#define AE_HMAX 1.0f
#endif
#ifndef AE_TGT
#define AE_TGT 0.045f
#endif
#ifndef AE_MIN
#define AE_MIN -1.0f
#endif
#ifndef AE_GMIN
#define AE_GMIN -0.5f
#endif
static int ae_hm[1024], ae_hx[1024];
static int ae_pct(const int* h, int n, int q1000) { int t = (int)((i64)n * q1000 / 1000), c = 0; for (int i = 0; i < 1024; ++i) { c += h[i]; if (c > t) return i; } return 1023; }
static const char* ae_meter(const u16* s, int rs, int w, int h, i64 now) {
    if (now - ae_last < 300000000LL && now >= ae_last) return 0;
    ae_last = now;
    int rsw = rs / 2; if (w < 64 || h < 64 || rsw < w) return 0;
    for (int i = 0; i < 1024; ++i) ae_hm[i] = ae_hx[i] = 0;
    int sx = (w / 128) & ~3, sy = (h / 96) & ~3; if (sx < 4) sx = 4; if (sy < 4) sy = 4;
    int n = 0, clip = 0; i64 sum = 0, csum = 0; int cn = 0;
    for (int y = sy / 2 & ~3; y + 4 <= h; y += sy) for (int x = sx / 2 & ~3; x + 4 <= w; x += sx) {
        int t = 0, mx = 0;
        for (int j = 0; j < 4; ++j) { const u16* r = s + (i64)(y + j) * rsw + x; for (int i = 0; i < 4; ++i) { int v = r[i]; t += v; if (v > mx) mx = v; } }
        int m = t >> 4; if (m > 1023) m = 1023; if (mx > 1023) mx = 1023;
        ae_hm[m]++; ae_hx[mx]++; sum += m; ++n; if (mx >= 1015) ++clip;
        if (x >= w / 3 && x < 2 * w / 3 && y >= h / 3 && y < 2 * h / 3) { csum += m; ++cn; }
    }
    if (n < 100) return 0;
    float med = (ae_pct(ae_hm, n, 500) + 0.5f - 64.f) / 959.f, avg = ((float)sum / n - 64.f) / 959.f;
    float ctr = cn ? ((float)csum / cn - 64.f) / 959.f : avg;
    float p99 = (ae_pct(ae_hx, n, 990) + 0.5f - 64.f) / 959.f, p995 = (ae_pct(ae_hx, n, 995) + 0.5f - 64.f) / 959.f;
    if (med < 1e-4f) med = 1e-4f; if (avg < 1e-4f) avg = 1e-4f; if (ctr < 1e-4f) ctr = 1e-4f; if (p99 < 1e-4f) p99 = 1e-4f; if (p995 < 1e-4f) p995 = 1e-4f;
    /* RawR-like rules, EV relative to this frame */
    float base = ae_log2(0.10f / med);                         /* matrix: median to 0.10 */
    float need = ae_log2(0.84f / p99) - base;                  /* after base, p99 must sit 0.25 EV below clip */
    float guard = need >= 0.f ? 0.f : (need < -4.f ? 0.f : (need < -1.5f ? -1.5f : need));
    float matrix = base + guard;
    float avgev = ae_log2(0.18f / avg), ctrev = ae_log2(0.18f / ctr), hiev = ae_log2(1.f / p995);
    if (hiev > 0.f) hiev = 0.f;                                 /* highlight mode: only reports needed darkening */
    /* P311 capture offset terms (EV, darken only): median above AE_TGT -> down to AE_MIN; p99 above 0.84 -> guard */
    { float mt = ae_log2(AE_TGT / med); ae_medt = mt > 0.f ? 0.f : (mt < AE_MIN ? AE_MIN : mt);
      float gd = ae_log2(0.84f / p99); ae_grd = gd > 0.f ? 0.f : (gd < AE_GMIN ? AE_GMIN : gd); }
    /* P315 highlight headroom: clipped share of the viewfinder raw -> lower the 50/25 MP frame ISO (GCam lifts the image
       back to its plan, the clipped glow keeps its gradient). 0.5 x log2(1 + clip/AE_HC) EV, <= AE_HMAX, from 0.1 % clipped */
    { int c10 = clip * 10000 / n; float hl = c10 < 10 ? 0.f : 0.5f * ae_log2(1.f + (float)c10 / AE_HC); if (hl > AE_HMAX) hl = AE_HMAX;
      float e = -hl, m = 1.f; while (e <= -1.f) { m *= 0.5f; e += 1.f; } m *= 1.f + e * (0.6931f + e * 0.1931f);  /* 2^e, e in (-1, 0] */
      ae_hs = 256.f * m; }
    char* o = ae_txt;
    nz_puts(&o, "ae w="); nz_puti(&o, w); nz_puts(&o, " h="); nz_puti(&o, h);
    nz_puts(&o, " med="); nz_puti(&o, (i64)(med * 1000)); nz_puts(&o, " avg="); nz_puti(&o, (i64)(avg * 1000));
    nz_puts(&o, " ctr="); nz_puti(&o, (i64)(ctr * 1000)); nz_puts(&o, " p99="); nz_puti(&o, (i64)(p99 * 1000));
    nz_puts(&o, " p995="); nz_puti(&o, (i64)(p995 * 1000)); nz_puts(&o, " clip10k="); nz_puti(&o, (i64)clip * 10000 / n);
    nz_puts(&o, " | ev base="); nz_puti(&o, (i64)(base * 100)); nz_puts(&o, " guard="); nz_puti(&o, (i64)(guard * 100));
    nz_puts(&o, " matrix="); nz_puti(&o, (i64)(matrix * 100)); nz_puts(&o, " avgm="); nz_puti(&o, (i64)(avgev * 100));
    nz_puts(&o, " ctrm="); nz_puti(&o, (i64)(ctrev * 100)); nz_puts(&o, " high="); nz_puti(&o, (i64)(hiev * 100));
    nz_puts(&o, " | xmed="); nz_puti(&o, (i64)(ae_medt * 100)); nz_puts(&o, " xgrd="); nz_puti(&o, (i64)(ae_grd * 100)); nz_puts(&o, " hs256="); nz_puti(&o, (i64)ae_hs);
    *o = 0; return ae_txt;
}
/* N.g(k): P311 last meter term, k 0 = median term, 1 = highlight guard (EV) */
__attribute__((visibility("default"))) float Java_TemporalBinning_00024N_g(JNIEnv* env, jobject cls, int k) { return k == 2 ? ae_hs : (k ? ae_grd : ae_medt); }
/* N.e(buffer, rowStride, w, h, nanoTime): P310 AE meter line, or null */
__attribute__((visibility("default"))) jobject Java_TemporalBinning_00024N_e(JNIEnv* env, jobject cls, jobject buf, int rs, int w, int h, i64 now) {
    GetAddr addr = (GetAddr)(*env)[230]; GetCap cap = (GetCap)(*env)[231];
    const u16* p = buf ? (const u16*)addr(env, buf) : 0;
    if (!p || cap(env, buf) < (i64)rs * (h - 1) + (i64)w * 2) return 0;
    const char* t = ae_meter(p, rs, w, h, now);
    return t ? ((NewStrUTF)(*env)[167])(env, t) : 0;
}
#endif
