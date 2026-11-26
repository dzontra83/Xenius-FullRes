#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <time.h>
#define HOST_TEST
#include "../tbin.c"
static void* thr(void* a) { mg_work(); return 0; }
int main(int argc, char** argv) {
    int N = 8, W = 8160, H = 6144;
    mg_begin(N, argc > 1 ? atoi(argv[1]) : 25);
    nzS = 0.0032; nzO = 2.4e-5; nzfit = 1;
    qj.w = W; qj.h = H; qj.mode = 0; qj.dnc = qj.dnl = 0; qj.nbands = 1; qj.doneC = 1;
    u16* b[8];
    for (int k = 0; k < N; ++k) {
        b[k] = (u16*)q_acquire(); char fn[32]; sprintf(fn, "f%d.raw", k);
        FILE* f = fopen(fn, "rb"); fread(b[k], 2, (size_t)OW * OH, f); fclose(f);
        mg_frame(b[k]);
    }
    printf("active=%d txt=%s\n", mg.active, mg_txt);
    struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
    pthread_t th[2]; for (int i = 0; i < 2; ++i) pthread_create(&th[i], 0, thr, 0);
    for (int i = 0; i < 2; ++i) pthread_join(th[i], 0);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    mg_finish();
    printf("%s  wall=%.2fs\n", mg_txt, (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) * 1e-9);
    for (int k = 1; k < N; ++k) printf("g%d %d %d (Bayer px %d %d)\n", k, mg.gdx[k], mg.gdy[k], 8*mg.gdx[k], 8*mg.gdy[k]);
    for (int k = 1; k < N; ++k) { int hx[9]={0}; int tot=0, ex=0; for (int t = 0; t < MG_TX*MG_TY; ++t) { if (t%MG_TX>=mg.tx || t/MG_TX>=mg.ty) continue; ++tot; } printf("frame %d gf %d %d tile0 sh %d %d mid %d %d\n", k, mg.gfx[k], mg.gfy[k], mg_sh[k][0][0], mg_sh[k][1][0], mg_sh[k][0][48*MG_TX+64], mg_sh[k][1][48*MG_TX+64]); }
    FILE* f = fopen("out.raw", "wb"); fwrite(b[3], 2, (size_t)OW * OH, f); fclose(f);
    int same = 1; for (int k = 1; k < N && same; ++k) for (long i = 0; i < (long)OW*OH; i += 9973) if (b[k][i] != b[0][i]) { same = 0; break; }
    printf("all frames identical: %d\n", same);
    return 0;
}
