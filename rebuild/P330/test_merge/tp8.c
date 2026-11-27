#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#define HOST_TEST
#include "../tbin.c"
static void* thr(void* a) { tbin_work(); return 0; }
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static int run(u16* src, u16* dst, int dnbits) {
    int rc = quad_start(src, OW * 2, 8160 | dnbits, 6128, dst); if (rc) return rc;
    pthread_t th[2]; for (int i = 0; i < 2; ++i) pthread_create(&th[i], 0, thr, 0);
    tbin_work(); for (int i = 0; i < 2; ++i) pthread_join(th[i], 0);
    return tbin_finish();
}
int main(int argc, char** argv) {
    int N = 8, mode = argc > 1 ? atoi(argv[1]) : 1;   /* 1 = premerge, 0 = single frame */
    int dnbits = (0 << 23) | (3 << 26);                 /* DNC 0, DNL 3 as the app */
    u16* raw[8]; u16* dst[8];
    for (int k = 0; k < N; ++k) {
        raw[k] = malloc((size_t)OW * OH * 2); char fn[32]; sprintf(fn, (argc > 2 && k == 0) ? argv[2] : (k == 5 ? "q5b.raw" : "q%d.raw"), k);
        FILE* f = fopen(fn, "rb"); fread(raw[k], 2, (size_t)OW * OH, f); fclose(f);
        dst[k] = (u16*)q_acquire();
    }
    nzS = 0; nzfit = 0;
    if (mode) { pm_begin(N, 25); for (int k = 0; k < N; ++k) pm_register(raw[k], OW * 2); }
    double t = now();
    for (int k = 0; k < (mode ? N : 1); ++k) {
        double t1 = now(); int rc = run(raw[k], dst[k], dnbits);
        printf("frame %d rc=%d %.2fs %s\n", k, rc, now() - t1, mg_txt); mg_txt[0] = 0;
    }
    printf("total %.2fs\n", now() - t);
    FILE* f = fopen(argc > 3 ? argv[3] : (mode ? "pm_out.raw" : "pm_single.raw"), "wb"); fwrite(dst[mode ? 3 : 0], 2, (size_t)OW * OH, f); fclose(f);
    if (mode) { int same = 1; for (int k = 1; k < N; ++k) if (memcmp(dst[k], dst[0], (size_t)OW * OH * 2)) same = 0; printf("identical=%d\n", same); }
    return 0;
}
