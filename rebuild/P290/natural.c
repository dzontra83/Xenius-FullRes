/* Natural QB 2x Bayer binning — C port of RawR app/src/main/cpp/renderer/NaturalBayerBin.h
   ("QB binning, adapted from a privately shared GPL-3.0 implementation (2026)", RawR is GPL-3.0-only).
   This file is therefore GPL-3.0. Freestanding: no libc, static scratch (single caller at a time).
   Samples are black-subtracted and scaled by one span (white - black); gains = camera WB gains / max. */

#define NB_H 20
#define NB_TW 256
#define NB_TH 64
#define NB_W (2 * NB_TW + 2 * NB_H)
#define NB_HH (2 * NB_TH + 2 * NB_H)
#define NB_N (NB_W * NB_HH)

#define NB_SLOTS 8
typedef struct { float p[10][NB_N]; float rows[7][NB_W]; float out[NB_TH * NB_TW]; float sm[NB_TW]; } nb_scratch;
static nb_scratch nb_s[NB_SLOTS];

static const float nb_chroma[9] = {.24695943f, .21372294f, .13419503f, .05120057f, 0,
                                   -.013715486f, -.0076747425f, -.0012080271f, 0};
static const float nb_luma[4] = {.125f, .375f, .375f, .125f};
static const float nb_soft[6] = {3.f / 128, 20.f / 128, 41.f / 128, 41.f / 128, 20.f / 128, 3.f / 128};
static const float nb_strong[10] = {1.f / 512, 9.f / 512, 36.f / 512, 84.f / 512, 126.f / 512,
                                    126.f / 512, 84.f / 512, 36.f / 512, 9.f / 512, 1.f / 512};
static const int nb_js[6] = {1, 2, 3, 5, 6, 7};

static inline int nb_reflect(int i, int n) {
    int period = 2 * (n - 1);
    i = (i % period + period) % period;
    return i < period - i ? i : period - i;
}
static inline float nb_clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

typedef struct { const unsigned short* src; int rsw, sw, sh; float black, span; } nb_ctx;
static inline float nb_sample(const nb_ctx* c, int x, int y) {
    return ((float)c->src[(long long)y * c->rsw + x] - c->black) / c->span;
}

static void nb_blur(float* a, float* tmp, int w, int h, int b, const float k[5]) {
    for (int y = b; y < h - b; ++y)
        for (int x = b + 2; x < w - b - 2; ++x) {
            int i = y * w + x; float v = 0;
            for (int j = 0; j < 5; ++j) v += a[i + j - 2] * k[j];
            tmp[i] = v;
        }
    for (int y = b + 2; y < h - b - 2; ++y)
        for (int x = b + 2; x < w - b - 2; ++x) {
            int i = y * w + x; float v = 0;
            for (int j = 0; j < 5; ++j) v += tmp[i + (j - 2) * w] * k[j];
            a[i] = v;
        }
}

static void nb_diag(const float* a, float* dst, int w, int h, int border, int s) {
    for (int y = border; y < h - border; ++y)
        for (int x = border; x < w - border; ++x) {
            int i = y * w + x;
            dst[i] = (a[i - 2 * s] + a[i + 2 * s] + 4 * (a[i - s] + a[i + s]) + 6 * a[i]) / 16;
        }
}

/* out[dy*stride+dx] for dx<tw, dy<th: binned values in sample units (black-subtracted / span) */
static void nb_tile(nb_scratch* S, const nb_ctx* c, int ox, int oy, int tw, int th, const float gains[4], int red, float flo,
                    float* out, int stride) {
    const int w = 2 * tw + 2 * NB_H, h = 2 * th + 2 * NB_H, H = NB_H;
    float (*nb_p)[NB_N] = S->p; float (*nb_rows)[NB_W] = S->rows;
    float *src = nb_p[0], *hx = nb_p[1], *hy = nb_p[2], *u = nb_p[3], *lum = nb_p[4], *v = nb_p[5],
          *ex = nb_p[6], *ey = nb_p[7], *tx = nb_p[8], *ty = nb_p[9];
    for (int k = 0; k < 10; ++k) for (int i = 0; i < w * h; ++i) nb_p[k][i] = 0;
    for (int y = 0; y < h; ++y) {
        int sy = nb_reflect(2 * oy + y - H, c->sh);
        const unsigned short* row = c->src + (long long)sy * c->rsw;
        float g0 = gains[2 * (sy & 1)] / c->span, g1 = gains[2 * (sy & 1) + 1] / c->span, bl = c->black;
        int x0 = 2 * ox - H;
        for (int x = 0; x < w; ++x) {
            int sx = x0 + x;
            if (sx < 0 || sx >= c->sw) sx = nb_reflect(sx, c->sw);
            src[y * w + x] = ((float)row[sx] - bl) * ((sx & 1) ? g1 : g0);
        }
    }
    for (int y = 0; y < h; ++y)
        for (int x = 8; x < w - 8; ++x) {
            int i = y * w + x;
            float even = src[i] * nb_chroma[0], odd = 0;
            for (int q = 0; q < 6; ++q) {
                int j = nb_js[q]; float a = (src[i - j] + src[i + j]) * nb_chroma[j];
                if (j & 1) odd += a; else even += a;
            }
            hx[i] = even + odd;
            hy[i] = (even - odd) * ((x & 1) == (red & 1) ? 1.f : -1.f);
        }
    for (int y = 8; y < h - 8; ++y)
        for (int x = 8; x < w - 8; ++x) {
            int i = y * w + x;
            float low = hy[i] * nb_chroma[0], hb = low, ha = hx[i] * nb_chroma[0];
            for (int q = 0; q < 6; ++q) {
                int j = nb_js[q];
                float b = (hy[i - j * w] + hy[i + j * w]) * nb_chroma[j];
                low += b;
                float s = (j & 1) ? -1.f : 1.f;
                hb += b * s;
                ha += (hx[i - j * w] + hx[i + j * w]) * nb_chroma[j] * s;
            }
            float s = (y & 1) == red / 2 ? 1.f : -1.f;
            u[i] = low; lum[i] = ha * s; v[i] = hb * s;
        }
    for (int y = 10; y < h - 10; ++y)
        for (int x = 10; x < w - 10; ++x) {
            int i = y * w + x;
            float gx = u[i + 2] - u[i - 2], gy = u[i + 2 * w] - u[i - 2 * w];
            ex[i] = gx * gx + gy * gy;
            gx = lum[i + 2] - lum[i - 2]; gy = lum[i + 2 * w] - lum[i - 2 * w];
            ey[i] = gx * gx + gy * gy;
        }
    static const float k1[5] = {.25f, 0, .5f, 0, .25f};
    nb_blur(ex, hx, w, h, 10, k1);
    nb_blur(ey, hx, w, h, 10, k1);
    for (int y = 12; y < h - 12; ++y)
        for (int x = 12; x < w - 12; ++x) {
            int i = y * w + x;
            float a = ex[i] + flo, b = ey[i] + flo, q = b / (a + b);
            float weight = q * q / (q * q + (1 - q) * (1 - q));
            u[i] = u[i] * weight + lum[i] * (1 - weight);
            float sx = (x & 1) == (red & 1) ? 1.f : -1.f, sy = (y & 1) == red / 2 ? 1.f : -1.f;
            lum[i] = src[i] - u[i] * (sx + sy) - v[i] * sx * sy;
        }
    for (int y = 13; y < h - 13; ++y)
        for (int x = 13; x < w - 13; ++x) {
            int i = y * w + x;
            float cc = 2 * lum[i], dx = lum[i + 1] - lum[i - 1], dy = lum[i + w] - lum[i - w];
            tx[i] = dx * dx - dy * dy;
            ty[i] = 2 * dx * dy;
            float cu = 0, gr = 0;
            int s1[2] = {1, w}, s2[2] = {w - 1, w + 1};
            for (int t = 0; t < 2; ++t) {
                int s = s1[t]; float d = lum[i - s] + lum[i + s] - cc, g = lum[i + s] - lum[i - s];
                cu += d * d; gr += g * g;
            }
            ex[i] = cu; ey[i] = gr; cu = 0; gr = 0;
            for (int t = 0; t < 2; ++t) {
                int s = s2[t]; float d = lum[i - s] + lum[i + s] - cc, g = lum[i + s] - lum[i - s];
                cu += d * d; gr += g * g;
            }
            hx[i] = cu; hy[i] = gr;
        }
    static const float k2[5] = {1.f / 16, 4.f / 16, 6.f / 16, 4.f / 16, 1.f / 16};
    float* bl[6] = {ex, ey, hx, hy, tx, ty};
    for (int t = 0; t < 6; ++t) nb_blur(bl[t], src, w, h, 13, k2);
    for (int y = 15; y < h - 15; ++y)
        for (int x = 15; x < w - 15; ++x) {
            int i = y * w + x;
            float trace = ey[i] + flo, a = tx[i] / trace, b = ty[i] / trace;
            float coh = nb_clampf((a * a + b * b - .25f) / .75f, 0.f, 1.f);
            coh *= coh;
            ex[i] = coh * nb_clampf(4 * (ex[i] - ey[i]) / (ex[i] + ey[i] + flo), 0.f, 1.f);
            hx[i] = coh * nb_clampf(4 * (hx[i] - .5f * hy[i]) / (hx[i] + hy[i] + flo), 0.f, 1.f);
        }
    nb_diag(lum, src, w, h, 14, w + 1);
    nb_diag(src, hy, w, h, 16, w - 1);
    float* fields[6] = {lum, u, v, ex, hy, hx};
    for (int dy = 0; dy < th; ++dy) {
        int y = H + 2 * dy;
        for (int x = H - 4; x < H + 2 * tw + 4; ++x) {
            for (int k = 0; k < 6; ++k) {
                const float* taps = k == 0 ? nb_luma : nb_soft;
                int n = k == 0 ? 4 : 6, left = k == 0 ? 1 : 2;
                float sum = 0;
                for (int j = 0; j < n; ++j) sum += fields[k][(y + j - left) * w + x] * taps[j];
                nb_rows[k][x] = sum;
            }
            float sum = 0;
            for (int j = 0; j < 10; ++j) sum += lum[(y + j - 4) * w + x] * nb_strong[j];
            nb_rows[6][x] = sum;
        }
        for (int dx = 0; dx < tw; ++dx) {
#define NBF(row, taps, n, left) ({ float s_ = 0; for (int j_ = 0; j_ < (n); ++j_) s_ += nb_rows[row][H + 2 * dx + j_ - (left)] * (taps)[j_]; s_; })
            float yl = NBF(0, nb_luma, 4, 1), uu = NBF(1, nb_soft, 6, 2), vv = NBF(2, nb_soft, 6, 2), risk = NBF(3, nb_soft, 6, 2);
            float yy = yl + risk * (NBF(6, nb_strong, 10, 4) - yl);
            yy += NBF(5, nb_soft, 6, 2) * (NBF(4, nb_soft, 6, 2) - yy);
#undef NBF
            int x = ox + dx, yout = oy + dy;
            float sx = (x & 1) == (red & 1) ? 1.f : -1.f, sy = (yout & 1) == red / 2 ? 1.f : -1.f;
            float value = (yy + uu * (sx + sy) + vv * sx * sy) / gains[2 * (yout & 1) + (x & 1)];
            int bx = 2 * x - (x & 1) - 4, by = 2 * yout - (yout & 1) - 4;
            float lo, hi;
            if (bx >= 0 && by >= 0 && bx + 10 < c->sw && by + 10 < c->sh) {      /* interior: no reflection */
                int mn = 65535, mxv = 0;
                for (int j = 0; j < 6; ++j) {
                    const unsigned short* r = c->src + (long long)(by + 2 * j) * c->rsw + bx;
                    for (int k = 0; k < 12; k += 2) { int a = r[k]; mn = a < mn ? a : mn; mxv = a > mxv ? a : mxv; }
                }
                lo = ((float)mn - c->black) / c->span; hi = ((float)mxv - c->black) / c->span;
            } else {
                lo = 1e30f; hi = -1e30f;
                for (int j = 0; j < 6; ++j)
                    for (int k = 0; k < 6; ++k) {
                        float a = nb_sample(c, nb_reflect(bx + 2 * k, c->sw), nb_reflect(by + 2 * j, c->sh));
                        lo = a < lo ? a : lo; hi = a > hi ? a : hi;
                    }
            }
            out[dy * stride + dx] = nb_clampf(value, lo, hi);
        }
    }
}


#ifndef BINMODE_NATURAL
/* RawR linear 2x Bayer bin (native/raw_ingress bayer_lin.comp pass 0, plain kernel; GPL-3.0): each output pixel
   is a fixed 12x12 weighted sum of the white-balanced mosaic around source (2X, 2Y), one weight set per output
   site, fitted to an anti-aliased 2x downscale with the 200 MP sensors' 4-px grid lines and 8x8 diagonal grid
   nulled. CPU port: source columns are split into the 4 phases (col mod 4) so every tap is a contiguous
   multiply-add over the tile row. Output: black-subtracted / span, not white-balanced (as nb_tile). */
#include "lin_kern.h"
#define LN_PW (NB_TW / 2 + 8)
typedef struct { float ph[12][4][LN_PW]; float acc[2][NB_TW / 2 + 4]; unsigned char cm[2][2 * NB_TW + 16]; } ln_scratch;
static ln_scratch ln_s[NB_SLOTS];
static void ln_tile(ln_scratch* S, const nb_ctx* c, int ox, int oy, int tw, int th, const float gains[4],
                    float* out, int stride) {
    float sc[4]; for (int i = 0; i < 4; ++i) sc[i] = gains[i] / c->span;
    const int base = 2 * ox - 5, nj = 2 * tw + 11;
    for (int dy = 0; dy < th; ++dy) {
        int Y = oy + dy;
        /* the 12 source rows of this output row, white-balanced, split by column phase */
        for (int ky = 0; ky < 12; ++ky) {
            int sy = 2 * Y - 5 + ky;
            sy = sy < 0 ? -sy : (sy >= c->sh ? 2 * c->sh - 2 - sy : sy);
            const unsigned short* row = c->src + (long long)sy * c->rsw;
            float s0 = sc[2 * (sy & 1)], s1 = sc[2 * (sy & 1) + 1], bl = c->black;
            for (int j = 0; j < nj; ++j) {
                int sx = base + j;
                if (sx < 0 || sx >= c->sw) sx = sx < 0 ? -sx : 2 * c->sw - 2 - sx;
                S->ph[ky][j & 3][j >> 2] = ((float)row[sx] - bl) * ((sx & 1) ? s1 : s0);
            }
        }
        /* clipped highlights: per source column, max raw over the 3 same-parity rows nearest the output
           (source rows 2Y-2 .. 2Y+3 = ky 3..8), by row parity */
        {
            const int thr = (int)(c->black + c->span) - 2;
            for (int j = 0; j < nj; ++j) { S->cm[0][j] = 0; S->cm[1][j] = 0; }
            for (int ky = 3; ky <= 8; ++ky) {
                int sy = 2 * Y - 5 + ky;
                sy = sy < 0 ? -sy : (sy >= c->sh ? 2 * c->sh - 2 - sy : sy);
                const unsigned short* row = c->src + (long long)sy * c->rsw; unsigned char* cmr = S->cm[sy & 1];
                for (int j = 0; j < nj; ++j) {
                    int sx = base + j;
                    if (sx < 0 || sx >= c->sw) sx = sx < 0 ? -sx : 2 * c->sw - 2 - sx;
                    if (row[sx] >= thr) cmr[j] = 1;
                }
            }
        }
        const int py = Y & 1, nm = (tw + 1) / 2;
        for (int p = 0; p < 2; ++p) {
            float* acc = S->acc[p];
            for (int m = 0; m < nm; ++m) acc[m] = 0;
            const float* K = lin_plain + (2 * py + ((ox + p) & 1)) * 144;
            for (int ky = 0; ky < 12; ++ky)
                for (int kx = 0; kx < 12; ++kx) {
                    const float k = K[ky * 12 + kx];
                    const int t = 2 * p + kx;
                    const float* src = &S->ph[ky][t & 3][t >> 2];
                    for (int m = 0; m < nm; ++m) acc[m] += k * src[m];
                }
        }
        for (int dx = 0; dx < tw; ++dx) {
            int X = ox + dx, p = dx & 1, px = X & 1;
            /* own-colour source samples in the 6x6 block around the output (cols j0..j0+5, col parity (j+1)&1);
               any of them clipped -> output clipped (2.f), so HDR+ sees a clipped pixel instead of a too-low
               value next to unclipped red/blue (magenta fringes on clipped sky) */
            int j0 = 2 * dx + 3, clip = 0;
            for (int j = j0; j < j0 + 6; ++j) {
                int cp = (j + 1) & 1;
                if (py == px) clip |= S->cm[py][j] & (cp == px);            /* R (0,0) / B (1,1) */
                else clip |= (S->cm[0][j] & (cp == 1)) | (S->cm[1][j] & (cp == 0));   /* G */
            }
            out[dy * stride + dx] = clip ? 2.f : S->acc[p][dx >> 1] / gains[2 * py + px];
        }
    }
}
#endif

/* job shared by all threads (prepare -> work on every thread -> finish) */
static struct { nb_ctx c; float gains[4]; float flo, black, white; unsigned short* dst; int ostride, ow, oh, bands, t256; } nb_job;
static void bin_seg(const unsigned short* src, int rsw, int sw, int sh, int y, int x0, int x1, float* out);
static int nb_next, nb_slot;

static void nb_prepare(const unsigned short* src, int rs, int sw, int sh, unsigned short* dst, int ostride,
                       float black, float white, const float wb[3], int t256) {
    nb_job.t256 = t256;
    nb_ctx c = {src, rs / 2, sw, sh, black, white - black};
    nb_job.c = c;
    float mx = wb[0]; if (wb[1] > mx) mx = wb[1]; if (wb[2] > mx) mx = wb[2];
    nb_job.gains[0] = wb[0] / mx; nb_job.gains[1] = nb_job.gains[2] = wb[1] / mx; nb_job.gains[3] = wb[2] / mx;  /* RGGB */
    float flo = (0.25f / c.span) * (0.25f / c.span); nb_job.flo = flo < 1e-20f ? 1e-20f : flo;
    nb_job.black = black; nb_job.white = white; nb_job.dst = dst; nb_job.ostride = ostride;
    nb_job.ow = sw / 2; nb_job.oh = sh / 2; nb_job.bands = (nb_job.oh + NB_TH - 1) / NB_TH;
    __atomic_store_n(&nb_next, 0, __ATOMIC_SEQ_CST); __atomic_store_n(&nb_slot, 0, __ATOMIC_SEQ_CST);
}

/* any number of threads: each grabs bands until none are left (4x code scale output, top-left of dst) */
static void nb_work(void) {
    int slot = __atomic_fetch_add(&nb_slot, 1, __ATOMIC_SEQ_CST);
    if (slot >= NB_SLOTS) return;
    nb_scratch* S = &nb_s[slot];
    for (;;) {
        int b = __atomic_fetch_add(&nb_next, 1, __ATOMIC_SEQ_CST);
        if (b >= nb_job.bands) return;
        int oy = b * NB_TH, th = nb_job.oh - oy < NB_TH ? nb_job.oh - oy : NB_TH;
        for (int ox = 0; ox < nb_job.ow; ox += NB_TW) {
            int tw = nb_job.ow - ox < NB_TW ? nb_job.ow - ox : NB_TW;
            int t256 = nb_job.t256; float ts = (float)t256 / 256.f;
#ifdef BINMODE_NATURAL
            if (t256 < 256) nb_tile(S, &nb_job.c, ox, oy, tw, th, nb_job.gains, 0, nb_job.flo, S->out, NB_TW);
#else
            if (t256 < 256) ln_tile(&ln_s[slot], &nb_job.c, ox, oy, tw, th, nb_job.gains, S->out, NB_TW);
#endif
            for (int y = 0; y < th; ++y) {
                if (t256 > 0) bin_seg(nb_job.c.src, nb_job.c.rsw, nb_job.c.sw, nb_job.c.sh, oy + y, ox, ox + tw, S->sm);
                for (int x = 0; x < tw; ++x) {
                    float v;                                                        /* in codes */
                    if (t256 < 256) {
                        float o = S->out[y * NB_TW + x];
                        if (o > 1.5f) v = nb_job.white;                      /* clipped (ln_tile) */
                        else {
                            v = o * nb_job.c.span + nb_job.black;
                            if (t256 > 0) v += (S->sm[x] - v) * ts;
                        }
                    } else v = S->sm[x];
                    v = v < 0 ? 0 : (v > nb_job.white ? nb_job.white : v);
                    nb_job.dst[(long long)(oy + y) * nb_job.ostride + ox + x] = (unsigned short)(v * 4.f + 0.5f);
                }
            }
        }
    }
}
