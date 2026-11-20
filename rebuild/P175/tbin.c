/* XENIUS P175 tbin: 200 MP RGGB RAW16 -> 50 MP Bayer, same-colour 2x bin.
   Kernel = RawR renderer/BayerBin.h binSameColor2x (sharp kernel, phase preserving, local min/max clamp).
   Output padded to 8192x6144 (edge sites repeated with the same CFA phase), 16-bit LE, row stride 16384 B.
   Freestanding: no libc; JNI through the function table. */
typedef unsigned short u16; typedef unsigned int u32; typedef long long i64;
#define OW 8192
#define OH 6144
static inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

/* bin one frame. src: sw x sh codes, row stride rs bytes. dst: OW x OH. black subtracted inside. */
/* one binned row (RawR BayerBin.h sharp kernel) of binned-row index y into out[0..bw) */
static void bin_row(const u16* src, int rsw, int sw, int sh, int y, float* out) {
    int bw = sw / 2;
    int ys[5], wy[5], ny, py = y & 1, cy = 2 * y;
    if (py) { ys[0]=cy-3; ys[1]=cy-1; ys[2]=cy+1; ys[3]=cy+3; wy[0]=1; wy[1]=19; wy[2]=19; wy[3]=1; ny=4; }
    else { ys[0]=cy-4; ys[1]=cy-2; ys[2]=cy; ys[3]=cy+2; ys[4]=cy+4; wy[0]=wy[4]=-2; wy[1]=wy[3]=5; wy[2]=14; ny=5; }
    const u16* rows[5];
    for (int j = 0; j < ny; ++j) rows[j] = src + (i64)clampi(ys[j], py, sh - 2 + py) * rsw;
    float dy = py ? 40.f : 20.f;
    for (int x = 0; x < bw; ++x) {
        int px = x & 1, cx = 2 * x;
        int xs[5], wx[5], nx;
        if (px) { xs[0]=cx-3; xs[1]=cx-1; xs[2]=cx+1; xs[3]=cx+3; wx[0]=1; wx[1]=19; wx[2]=19; wx[3]=1; nx=4; }
        else { xs[0]=cx-4; xs[1]=cx-2; xs[2]=cx; xs[3]=cx+2; xs[4]=cx+4; wx[0]=wx[4]=-2; wx[1]=wx[3]=5; wx[2]=14; nx=5; }
        if (x < 2 || x >= bw - 2) for (int i = 0; i < nx; ++i) xs[i] = clampi(xs[i], px, sw - 2 + px);
        int sum = 0, lo = 65535, hi = 0;
        for (int j = 0; j < ny; ++j) {
            const u16* r = rows[j]; int rsum = 0;
            for (int i = 0; i < nx; ++i) { int v = r[xs[i]]; rsum += wx[i] * v; lo = v < lo ? v : lo; hi = v > hi ? v : hi; }
            sum += wy[j] * rsum;
        }
        float v = (float)sum / ((px ? 40.f : 20.f) * dy);
        if (v < lo) v = lo; if (v > hi) v = hi;
        out[x] = v;
    }
}

/* bin 2x, then stretch the binned Bayer image to OW x OH (same-colour linear interpolation, CFA phase kept).
   8160 -> 8192 and 6128 -> 6144 is a 0.4 % / 0.26 % stretch: no padding streaks at the edges. */
#define MAXBW 8192
int tbin_run(const u16* src, int rs, int sw, int sh, u16* dst, int black, int white) {
    if (sw < 64 || sh < 64 || (sw & 3) || (sh & 3) || rs < sw * 2) return 2;
    int bw = sw / 2, bh = sh / 2;
    if (bw > OW || bh > OH || bw > MAXBW) return 3;
    int rsw = rs / 2;
    static float cache[4][MAXBW]; int cidx[4] = {-1, -1, -1, -1}; int cnext = 0;
    static int xi0[OW], xi1[OW]; static float xf[OW];
    /* horizontal map: dest lattice j (per parity) -> binned lattice position */
    int Lbw = bw / 2, Ldw = OW / 2, Lbh = bh / 2, Ldh = OH / 2;
    for (int x = 0; x < OW; ++x) {
        int p = x & 1, j = x >> 1;
        float t = (Ldw > 1) ? (float)j * (float)(Lbw - 1) / (float)(Ldw - 1) : 0.f;
        int k0 = (int)t; if (k0 > Lbw - 1) k0 = Lbw - 1;
        int k1 = k0 + 1 < Lbw ? k0 + 1 : Lbw - 1;
        xi0[x] = 2 * k0 + p; xi1[x] = 2 * k1 + p; xf[x] = t - (float)k0;
    }
    for (int y = 0; y < OH; ++y) {
        int p = y & 1, j = y >> 1;
        float t = (Ldh > 1) ? (float)j * (float)(Lbh - 1) / (float)(Ldh - 1) : 0.f;
        int k0 = (int)t; if (k0 > Lbh - 1) k0 = Lbh - 1;
        int k1 = k0 + 1 < Lbh ? k0 + 1 : Lbh - 1;
        float fy = t - (float)k0;
        int r[2] = {2 * k0 + p, 2 * k1 + p}; float* rp[2];
        for (int q = 0; q < 2; ++q) {
            int hit = -1;
            for (int c = 0; c < 4; ++c) if (cidx[c] == r[q]) hit = c;
            if (hit < 0) { hit = cnext; cnext = (cnext + 1) & 3; cidx[hit] = r[q]; bin_row(src, rsw, sw, sh, r[q], cache[hit]); }
            rp[q] = cache[hit];
        }
        /* protect the second row from eviction by the first lookup: 4 slots, at most 2 new rows per y */
        u16* out = dst + (i64)y * OW;
        for (int x = 0; x < OW; ++x) {
            float a = rp[0][xi0[x]] + (rp[0][xi1[x]] - rp[0][xi0[x]]) * xf[x];
            float b = rp[1][xi0[x]] + (rp[1][xi1[x]] - rp[1][xi0[x]]) * xf[x];
            float v = a + (b - a) * fy;
            int iv = (int)(v + 0.5f); out[x] = (u16)(iv < 0 ? 0 : (iv > 65535 ? 65535 : iv));
        }
    }
    (void)black; (void)white;
    return 0;
}

#ifndef HOST_TEST
typedef void* jobject; typedef const void* const* JNIEnv;
typedef void* (*GetAddr)(JNIEnv*, jobject);
typedef i64 (*GetCap)(JNIEnv*, jobject);
void* memset(void* d, int c, unsigned long n) { unsigned char* p = d; while (n--) *p++ = (unsigned char)c; return d; }
void* memcpy(void* d, const void* s, unsigned long n) { unsigned char* p = d; const unsigned char* q = s; while (n--) *p++ = *q++; return d; }
__attribute__((visibility("default"))) int Java_TemporalBinning_00024N_b(JNIEnv* env, jobject cls, jobject src, int rs, int w, int h, jobject dst) {
    GetAddr addr = (GetAddr)(*env)[230]; GetCap cap = (GetCap)(*env)[231];
    const u16* s = (const u16*)addr(env, src); u16* d = (u16*)addr(env, dst);
    if (!s || !d) return 10;
    if (cap(env, dst) < (i64)OW * OH * 2) return 11;
    if (cap(env, src) < (i64)rs * (h - 1) + (i64)w * 2) return 12;
    int rc = tbin_run(s, rs, w, h, d, 64, 1023);
    /* mean of the source (sparse grid) in the upper bits, for the log */
    i64 sum = 0, n = 0;
    for (int y = 16; y < h; y += 257) for (int x = 16; x < w; x += 263) { sum += s[(i64)y * (rs / 2) + x]; ++n; }
    int mean = n ? (int)(sum / n) : 0;
    i64 dsum = 0;
    for (int y = 8; y < OH; y += 131) for (int x = 8; x < OW; x += 127) dsum += d[(i64)y * OW + x];
    int dmean = (int)(dsum / ((i64)((OH - 8 + 130) / 131) * ((OW - 8 + 126) / 127)));
    return rc | (mean & 4095) << 8 | (dmean & 4095) << 20;
}
#endif
